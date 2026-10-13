import genlayer as gl
from genlayer import *
import json

class CryptoJudge(gl.contract.Contract):
    weekly_fee: u256
    verdict: str

    def __init__(self):
        self.weekly_fee = 0
        self.verdict = "BEKLIYOR"

    @gl.public.write
    def refresh(self) -> None:

        def fetch_fee() -> int:
            url = "https://api.llama.fi/summary/fees/aerodrome?dataType=dailyFees"
            response = gl.nondet.web.get(url)
            data = json.loads(response.body.decode("utf-8"))
            return int(data["total7d"])

        fee = gl.eq_principle.strict_eq(fetch_fee)

        self.weekly_fee = fee
        self.verdict = "EVET" if fee > 5000000 else "HAYIR"

    @gl.public.view
    def get_verdict(self) -> str:
        return self.verdict

    @gl.public.view
    def get_weekly_fee(self) -> int:
        return self.weekly_fee
