import warnings

import pytest

from replyanalysis.pipeline import run
from replyanalysis.prepare import AnalysisConfig, load_inputs
from replyanalysis.synthetic import Effects, generate, null_effects, write_dataset

warnings.filterwarnings("ignore")

FAST = dict(bootstrap=300, pod_permutations=120)


def _dataset(tmp_path_factory, name, effects, n=36, seed=7, include_text=False):
    out = tmp_path_factory.mktemp(name)
    paths = write_dataset(out, generate(n, seed, effects, include_text=include_text))
    inp = load_inputs([paths["captures_dir"]], paths["codes"], None, paths["threads"], paths["root_codes"],
                      paths["authors"], paths["captures"])
    return paths, inp


@pytest.fixture(scope="session")
def effect_world(tmp_path_factory):
    strong = Effects(outrage_reach=1.2, insult_penalty=1.0, insult_large_rescue=1.5, clipper_outrage_logit=2.0,
                    pileon_follower_growth=0.3)
    paths, inp = _dataset(tmp_path_factory, "effects", strong, include_text=True)
    return paths, run(inp, AnalysisConfig(**FAST))


@pytest.fixture(scope="session")
def null_world(tmp_path_factory):
    paths, inp = _dataset(tmp_path_factory, "null", null_effects(), seed=11)
    return paths, run(inp, AnalysisConfig(**FAST))


def by_id(results):
    return {t["id"]: t for t in results["confirmatory"]}
