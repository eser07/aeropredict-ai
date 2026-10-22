# Completed-epoch verification for the fixed 950-pool cohort

## Completed delivery — 22 October 2026

All 950 raw pool claims are VERIFIED on stable Hosted Studio 61999. Contract: 0x5cEaA656912AE207288c79afA605b7F129Ad220C. Exactly one deployment and 95 verify_batch writes used all 96 authorized broadcast attempts. Every transaction is FINALIZED with at least three agree votes. Execution read every pool result; a separate audit checked the source, full 950 summary, all 96 receipts and independent pool-view samples. Evidence is in studio_runs/hosted_20261022/; no execution replay is authorized.

Source SHA256: b835f9a011c785f780576f09e56f9399b8bbccca11c6121357a053ddbce43436. Merkle root: 7928f8b2b2785df66a0eb8722427ccf891bf9bc37c50c125389e5065eab88786. The approved plan and earlier local/preparation evidence remain unchanged.

## Collection and attestation scope

../../scripts/collect_epoch_950.py collected four epoch keys starting 24 September, 1 October, 8 October and 15 October, ending 22 October 2026 00:00 UTC. Every Base eth_call was pinned with requireCanonical=true to finalized block 52929586 / 0x2d62018d94b4b1c45ea3c7e009bc0229738d8cb49c8232b739effe0a91d9b6c5. This is one post-period finalized state, not four historical boundary-state reconstructions.

Raw append-only checkpoints are under ../../data/epoch_950_runs/2026-10-22/block_52929586_2d62018d. The run is complete; do not overwrite or replay it. These are the fixed earlier 950 identities, not a current alive-gauge count. All 950 pool reads completed without reported errors. USD coverage: 910 complete / 40 incomplete; 224 had no observed rewards. Prices are separate collection-time DefiLlama observations, not historical-week USD prices or validator-verified USD. Unknown USD is not zero.

Epoch950Verifier compares pool/gauge/reward mappings, DURATION, full token registries and four weeks of raw token amounts against validator web reads of the pinned Base block. USD, pair metadata, earlier votes, forecast outcomes and personal veAERO income are outside this attestation. No LLM calls occur. Hosted Studio is a shared development simulator; its validator majority is not independent public-network operator consensus or a durable public-chain timestamp.

## Verification evidence and boundaries

Eight offline preparation tests, one local ten-pool runtime batch and 30 current website checks are separate from the 96 remote transactions. Prior P9/P10 tests were not rerun. The original local Studio volume, historical files and user script changes are preserved. Protocol GEN and total USD costs remain unknown/null; see cost_reports/hosted_20261022.md.

The first runner stopped after finalized batch45 during a transient read. Recovery re-read that finalized batch and sent only the remaining 49 writes. No finalized or ambiguous write was repeated; the total remained 96. Temporary private keys were not stored. No faucet, personal wallet, real funds, paid service, other network or settlement was used.

## Publication

https://aeropredict.app/ now serves the 22 October data and one detailed 950-pool list. /pilot#pilot exposes each pool's recorded result, raw Merkle proof and live read-only source/result/receipt comparison. Public Site version4, source a325022d05a60574aaefa7a38eadcf35a61cba92, deployment appgdep_6ad9dc6214fc8191bc18c06be9ea21ea succeeded at 2026-10-22T09:50:44.588031Z. Sites source and canonical GitHub are separate repositories; no new canonical GitHub push was made.

At the user's request, original five forecasts, old probe and their public assets/readers were removed from the website. Canonical registrations and on-chain history are preserved. Their original 22–29 October period remains separate and was not settled by this completed 15–22 October observation. No new remote write, settlement or automatic future public push is authorized by this completed plan.
