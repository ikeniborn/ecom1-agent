from bitgn._connect import ConnectClient
from bitgn.harness_pb2 import (
    StatusRequest, StatusResponse,
    GetBenchmarkRequest, GetBenchmarkResponse,
    StartPlaygroundRequest, StartPlaygroundResponse,
    StartRunRequest, StartRunResponse,
    GetRunRequest, GetRunResponse,
    StartTrialRequest, StartTrialResponse,
    GetTrialRequest, GetTrialResponse,
    EndTrialRequest, EndTrialResponse,
    SubmitRunRequest, SubmitRunResponse,
)

_SERVICE = "bitgn.harness.HarnessService"


class HarnessServiceClientSync:
    def __init__(self, base_url: str):
        self._c = ConnectClient(base_url)

    def status(self, req: StatusRequest) -> StatusResponse:
        return self._c.call(_SERVICE, "Status", req, StatusResponse)

    def get_benchmark(self, req: GetBenchmarkRequest) -> GetBenchmarkResponse:
        return self._c.call(_SERVICE, "GetBenchmark", req, GetBenchmarkResponse)

    def start_playground(self, req: StartPlaygroundRequest) -> StartPlaygroundResponse:
        return self._c.call(_SERVICE, "StartPlayground", req, StartPlaygroundResponse)

    def start_run(self, req: StartRunRequest) -> StartRunResponse:
        return self._c.call(_SERVICE, "StartRun", req, StartRunResponse)

    def get_run(self, req: GetRunRequest) -> GetRunResponse:
        return self._c.call(_SERVICE, "GetRun", req, GetRunResponse)

    def start_trial(self, req: StartTrialRequest) -> StartTrialResponse:
        return self._c.call(_SERVICE, "StartTrial", req, StartTrialResponse)

    def get_trial(self, req: GetTrialRequest) -> GetTrialResponse:
        return self._c.call(_SERVICE, "GetTrial", req, GetTrialResponse)

    def end_trial(self, req: EndTrialRequest) -> EndTrialResponse:
        return self._c.call(_SERVICE, "EndTrial", req, EndTrialResponse)

    def submit_run(self, req: SubmitRunRequest) -> SubmitRunResponse:
        return self._c.call(_SERVICE, "SubmitRun", req, SubmitRunResponse)
