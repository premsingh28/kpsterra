"""Write reference results from the Python implementation for the browser test page (frontend/tests/)."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT  # noqa: E402
from app.services import climate as C  # noqa: E402

rng = np.random.default_rng(7)
n = 80
x1 = rng.normal(size=n)
x2 = 0.4 * x1 + rng.normal(size=n)
y = 1.5 + 0.8 * x1 - 0.5 * x2 + rng.normal(size=n)
y[[5, 17]] = np.nan
ties = np.round(rng.normal(size=n), 1)
months = np.tile(np.arange(1, 13), 7)[:n]
clean = lambda a: [None if np.isnan(v) else float(v) for v in a]  # noqa: E731

strip = lambda d: {k: v for k, v in d.items() if k not in ("x", "y")}  # noqa: E731
fixture = {
    "inputs": {"x1": clean(x1), "x2": clean(x2), "y": clean(y), "ties": clean(ties), "months": months.tolist()},
    "expected": {
        "pearson": strip(C.correlate(x1, y, "pearson")),
        "spearman_ties": strip(C.correlate(ties, y, "spearman")),
        "deseason": clean(C.deseasonalise(y, months)),
        "deseason_std": clean(C.deseasonalise(y, months, True)),
        "detrend": clean(C.detrend(y)),
        "ols": C.ols(y, [x1, x2], ["x1", "x2"]),
    },
}
out = ROOT / "frontend" / "tests" / "fixture.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(fixture))
print("wrote", out)
