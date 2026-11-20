import time
from vcommon import *
t0=time.time()
market, cells, intents = setup()
for seed in (1, 7, 42, 2026):
    with store.ceiling(VALIDATION_END):
        r = harness.leak_test(STRATEGY, market.data, full_by_cell=intents, n_targeted=120, n_other=6, seed=seed)
    print("seed", seed, {k: r[k] for k in ("passed","mismatches","probes","cells","forbidden_code")}, round(time.time()-t0,1), flush=True)
# universe timing: recompute three months from daily volume, reading only rows before VALIDATION_END
import pyarrow.parquet as pq, pyarrow as pa
pf = pq.ParquetFile(ROOT/"data/daily_volume.parquet")
print(pf.schema_arrow)
