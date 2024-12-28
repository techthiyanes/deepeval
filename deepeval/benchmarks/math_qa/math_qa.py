from datasets import load_dataset
from typing import List, Optional, Dict
from tqdm import tqdm
import pandas as pd

from deepeval.dataset import Golden
from deepeval.benchmarks.base_benchmark import DeepEvalBaseBenchmark
from deepeval.models import DeepEvalBaseLLM
from deepeval.benchmarks.math_qa.task import MathQATask
from deepeval.benchmarks.math_qa.template import MathQATemplate
from deepeval.benchmarks.utils import should_use_batch
from deepeval.scorer import Scorer
from deepeval.benchmarks.schema import MultipleChoiceSchemaLower
from deepeval.telemetry import capture_benchmark_run


class MathQA(DeepEvalBaseBenchmark):
    def __init__(
        self, tasks: List[MathQATask] = None, n_shots: int = 5, **kwargs
    ):
        assert n_shots <= 5, "MathQA only supports n_shots <= 5"
        super().__init__(**kwargs)
        self.tasks: List[MathQATask] = (
            list(MathQATask) if tasks is None else tasks
        )
        self.scorer = Scorer()
        self.n_shots: int = n_shots
        self.predictions: Optional[pd.DataFrame] = None
        self.task_scores: Optional[pd.DataFrame] = None
        self.overall_score: Optional[float] = None

    def evaluate(
        self, model: DeepEvalBaseLLM, batch_size: Optional[int] = None
    ) -> Dict:
        with capture_benchmark_run("MathQA", len(self.tasks)):
            overall_correct_predictions = 0
            overall_total_predictions = 0
            predictions_row = []
            scores_row = []
            use_batch = should_use_batch(model, batch_size)

            for task in self.tasks:
                goldens = self.load_benchmark_dataset(task)[:10]
                task_correct_predictions = 0
                task_total_predictions = len(goldens)
                overall_total_predictions += len(goldens)

                # Calculate task accuracy
                if use_batch:
                    for i in tqdm(
                        range(0, len(goldens), batch_size),
                        desc=f"Batch Processing {task.value} (batch_size={batch_size})",
                    ):
                        goldens_batch = goldens[i : i + batch_size]
                        batch_predictions = self.batch_predict(
                            model, goldens_batch
                        )
                        for golden, prediction_dict in zip(
                            goldens_batch, batch_predictions
                        ):
                            prediction = prediction_dict["prediction"]
                            score = prediction_dict["score"]
                            if score:
                                task_correct_predictions += 1
                                overall_correct_predictions += 1
                            predictions_row.append(
                                (task.value, golden.input, prediction, score)
                            )
                else:
                    for golden in tqdm(
                        goldens, desc=f"Processing {task.value}"
                    ):
                        prediction, score = self.predict(model, golden).values()
                        if score:
                            task_correct_predictions += 1
                            overall_correct_predictions += 1
                        predictions_row.append(
                            (task.value, golden.input, prediction, score)
                        )

                task_accuracy = (
                    task_correct_predictions / task_total_predictions
                )
                print(
                    f"MathQA Task Accuracy (task={task.value}): {task_accuracy}"
                )
                scores_row.append((task.value, task_accuracy))

            # Calculate overall accuracy
            overall_accuracy = (
                overall_correct_predictions / overall_total_predictions
            )
            print(f"Overall MathQA Accuracy: {overall_accuracy}")

            # Create a DataFrame from task_results_data
            # Columns: 'Task', 'Input', 'Prediction', 'Score'
            self.predictions = pd.DataFrame(
                predictions_row,
                columns=["Task", "Input", "Prediction", "Correct"],
            )
            self.task_scores = pd.DataFrame(
                scores_row, columns=["Task", "Score"]
            )
            self.overall_score = overall_accuracy

            return overall_accuracy

    def predict(self, model: DeepEvalBaseLLM, golden: Golden) -> Dict:
        # Define prompt template
        prompt: dict = MathQATemplate.generate_output(
            input=golden.input,
            n_shots=self.n_shots,
        )

        # Enforced model generation
        try:
            res: MultipleChoiceSchemaLower = model.generate(
                prompt=prompt, schema=MultipleChoiceSchemaLower
            )
            prediction = res.answer
        except TypeError:
            prompt += (
                "\n\nOutput 'a', 'b', 'c', or 'd'. Full answer not needed."
            )
            prediction = model.generate(prompt)

        # For native models, shouldn't happen but just in case
        if isinstance(prediction, tuple):
            prediction = prediction[0]

        # Define Metric
        score = self.scorer.exact_match_score(
            golden.expected_output, prediction
        )
        return {"prediction": prediction, "score": score}

    def batch_predict(
        self, model: DeepEvalBaseLLM, goldens: List[Golden]
    ) -> List[Dict]:
        # Define prompt template
        prompts = []
        for golden in goldens:
            prompt: dict = MathQATemplate.generate_output(
                input=golden.input,
                n_shots=self.n_shots,
            )
            prompts.append(prompt)

        # Enforced model generation
        try:
            responses: List[MultipleChoiceSchemaLower] = model.batch_generate(
                prompts=prompts,
                schemas=[MultipleChoiceSchemaLower for _ in prompts],
            )
            predictions = [res.answer for res in responses]
        except TypeError:
            prompts = [
                prompt
                + "\n\nOutput 'a', 'b', 'c', or 'd'. Full answer not needed."
                for prompt in prompts
            ]
            predictions = model.batch_generate(prompts)

        if len(predictions) is not len(goldens):
            raise ValueError(
                "Custom `batch_generate` method did not return the same number of generations as the number of prompts."
            )

        res = []
        for i in range(len(predictions)):
            prediction = predictions[i]
            golden = goldens[i]
            # Define Metric
            score = self.scorer.exact_match_score(
                golden.expected_output, prediction
            )
            res.append({"prediction": prediction, "score": score})

        return res

    def load_benchmark_dataset(self, task: MathQATask) -> List[Golden]:
        dataset = load_dataset("allenai/math_qa", trust_remote_code=True)
        self.dataset = dataset

        # Construct test set
        test_set = dataset["test"].filter(
            lambda data: data["category"] == task.value
        )
        goldens: List[Golden] = []
        for data in test_set:
            input = MathQATemplate.format_question(data, include_answer=False)
            expected_output = MathQATemplate.format_output(data)
            golden = Golden(input=input, expected_output=expected_output)
            goldens.append(golden)
        return goldens
