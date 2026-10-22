# Completed-epoch verification for the fixed 950-pool cohort

## Collection

`../../scripts/collect_epoch_950.py` collected the four epoch keys ending 2026-10-22 00:00 UTC. Every Base `eth_call` used block 52929586 / 0x2d62018d94b4b1c45ea3c7e009bc0229738d8cb49c8232b739effe0a91d9b6c5 with requireCanonical=true. This is a single post-period finalized state, not four historical boundary-state reconstructions.

Raw append-only checkpoints and raw_dataset.json are under `../../data/epoch_950_runs/2026-10-22/block_52929586_2d62018d`. That run is complete; do not replay it or overwrite its files. The 950 identities are the earlier research cohort, not the current alive-gauge count. Pair labels and earlier vote observations retain their original provenance.

All 950 pool reads completed without reported errors. USD coverage is 910 complete / 40 incomplete. DefiLlama token quotes are a separate observation at collection time, not historical week prices. Unknown USD is not zero.

## Proposed validator contract

Epoch950Verifier pins the exact 950 raw claims through a Merkle root. verify_batch reconstructs identities, reward mappings, DURATION, full token lists and four tokenRewardsPerEpoch values, then asks GenVM validators to fetch the same Base block and apply strict equivalence. USD quotes, token metadata and forecast accuracy are outside this attestation. No LLM calls occur.

Local Studio 61127 tested this exact source against a ten-pool batch: FINALIZED, 3 agree / 2 idle, ten VERIFIED results. Offline tests reconstruct every one of the 950 claims against saved raw RPC responses, independently compare ABI encoding with eth_abi, and reject forged proofs, truncated registries, missing amounts, failed calls and duplicate writes. Offline SDK stubs are not consensus evidence.

`prepare_epoch950_plan.py --run <raw-run-directory> --out <new-output-directory>` rebuilds payloads and runs eight offline tests. Dependencies: eth_abi, eth_utils. It does not submit transactions. The pure contract is tested through a stubbed SDK in that process only; real runtime evidence is separate.

## Remote boundary

The plan proposes one new Hosted Studio 61999 deployment plus 95 writes, at most ten pools each, and at most 96 broadcast attempts. New explicit human approval is required. Original approval for six deployments plus one probe is consumed. The local integration is not proof that all 950 pools were remotely validated. Stable legacy gasPrice is zero, but protocol GEN and total USD cost remain unknown/null. No real funds, personal wallet, paid RPC/LLM, faucet, other network or forecast settlement is authorized by this preparation.

Hosted Studio is a shared development simulator, not independent public-network operator consensus. The five original 22–29 October forecast registrations are unchanged and remain pending. This completed 15–22 October reward observation does not settle them.

## Publication

The prepared review website uses the fresh snapshot, neutral search, and all950 verification status. It has not been pushed or deployed in this preparation. Future publication requires the concrete Sites push approval. Canonical GitHub push is excluded.
