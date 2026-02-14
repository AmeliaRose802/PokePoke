"""Setup configuration for PokePoke."""

from setuptools import setup, find_packages

setup(
    name="pokepoke",
    version="0.1.0",
    description="Autonomous Beads + Copilot CLI Orchestrator",
    author="Amelia Payne",
    python_requires=">=3.12",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={
        "console_scripts": [
            "pokepoke=pokepoke.orchestrator:main",
            "pokepoke-init=pokepoke.init:main",
        ],
    },
)
