import pytest
from pathlib import Path

SAMPLE_F3Z = Path(__file__).parent.parent / "examples" / "IOMOD-AD5593R-v2_0.f3z"


@pytest.fixture(scope="session")
def sample_f3z():
    return SAMPLE_F3Z
