import logging
from client.base import DatasetAlias, DatasetIterator
from client.triton_client import TritonClient
from timeit import default_timer as timer

LOG = logging.getLogger(__name__)

class RunnerConfig:

    def __init__(self, batch_size: int = 1, async_req: bool = False) -> None:
        self.batch_size = batch_size
        self.async_req = async_req

class Runner:

    def __init__(self, cfg: RunnerConfig, client: TritonClient, dataset: DatasetAlias) -> None:
        self.config = cfg
        self.client = client
        self.dataset = DatasetIterator(dataset, infinite=False)
        self.execution_times = []
    
    def run(self):
        LOG.info("Starting client runner")
        def send_batch(batch):
            LOG.debug("Sending batch of size %d", len(batch))
            start = timer()
            if self.config.async_req:
                res = self.client.infer_batch_async(batch)
                LOG.debug("Received response %s", res.get_result())
            else:
                res = self.client.infer_batch(batch)
                LOG.debug("Received response %s", res.get_response())
            end = timer()
            self.execution_times.append(end - start)
            batch.clear()
        
        batch = []
        for sample in self.dataset:
            batch.append(sample)
            if len(batch) == self.config.batch_size:
              send_batch(batch)
        if len(batch) > 0:
            send_batch(batch)
        LOG.info("Finished client runner")
          # Convert execution times to a numpy array
        execution_times = self.execution_times
        self.execution_times = []
        return execution_times
             
         