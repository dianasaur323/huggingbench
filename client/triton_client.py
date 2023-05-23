import time
import logging
import json
from prometheus_client import start_http_server, Counter, Histogram, Info
import tritonclient.http as httpclient
from tritonclient.utils import triton_to_np_dtype
import numpy as np

LOG = logging.getLogger(__file__)
TRITON_SERVER = "localhost:8000"
MODEL_VERSION = "1"
PROM_PORT = 8011  # Prometheus port


class TritonClient:
    """ Runs the given function in locust and records metrics """
    metric_infer_latency = Histogram(
        "infer_latency", "Latency for inference in seconds", labelnames=["model"])
    metric_infer_requests = Counter(
        "infer_requests", "Number of inference requests", labelnames=["model"])
    metric_info = Info("client_info", "Information about the client")
    LOG.info("Starting Prometheus server on port 8001")
    start_http_server(PROM_PORT)

    def __init__(self, triton_url: str, model_name: str):
        self._server_url = triton_url
        # we can't have "/" in the model file path
        escaped_model_name = model_name.replace("/", "-")
        self.model = escaped_model_name + "-onnx"  # TODO: ONNX suffix hardcoded
        self.model_version = MODEL_VERSION
        self.metric_info.info({"model": self.model})
        LOG.info("Creating triton client for server: %s", self._server_url)
        self.client = httpclient.InferenceServerClient(url=self._server_url)
        errors = self._server_check(self.client)
        if errors:
            raise RuntimeError(f"Triton Server check failed: {errors}")
        LOG.info("Triton server check successful. Server is ready to handle requests")
        model_config = self.client.get_model_config(
            self.model, self.model_version)
        model_metadata = self.client.get_model_metadata(
            self.model, self.model_version)
        LOG.info("Model config: %s", json.dumps(model_config, indent=4))
        LOG.info("Model metadata: %s", json.dumps(model_metadata, indent=4))

        self.inputs = {tm["name"]: tm for tm in model_metadata["inputs"]}
        self.outputs = {tm["name"]: tm for tm in model_metadata["outputs"]}

    def infer(self, sample) -> httpclient.InferResult:
        """ Runs inference on the triton server """
        self.metric_infer_requests.labels(self.model).inc()
        with self.metric_infer_latency.labels(self.model).time():
            return self.infer_req(sample=sample)

    def infer_req(self, sample) -> httpclient.InferResult:
        infer_inputs = []
        infer_outputs = []
        for input in self.inputs:
            data_type = self.inputs[input]["datatype"]
            np_dtype = triton_to_np_dtype(
                data_type)
            data = sample[input].astype(np_dtype)
            # adding batch dimension
            data = np.expand_dims(data, axis=0)
            # we need to adjust shape for batching (batch size = 1)
            shape = (1,) + sample[input].shape
            infer_input = httpclient.InferInput(
                input, shape, data_type)
            infer_input.set_data_from_numpy(
                data)
            infer_inputs.append(infer_input)
        for output in self.outputs:
            infer_outputs.append(
                httpclient.InferRequestedOutput(output))
        infer_res: httpclient.InferResult = self.client.infer(
            model_name=self.model, model_version=self.model_version,
            inputs=infer_inputs, outputs=infer_outputs)
        return infer_res

    def _server_check(self, client):
        errors = []
        if not client.is_server_live():
            errors.append(f"Triton server {self._server_url} is not up")
        if not client.is_server_ready():
            errors.append(f"Triton server {self._server_url} is not ready")
        if not client.is_model_ready(self.model, self.model_version):
            errors.append(
                f"Model {self.model}:{self.model_version} is not ready")
        return errors