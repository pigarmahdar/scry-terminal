from setuptools import find_packages, setup

setup(
    name="scry-terminal",
    version="1.0.0",
    description="Instant, offline Magic: The Gathering card lookups and deck diagnostics from your terminal.",
    author="Pigar Mahdar",
    license="MIT",
    packages=find_packages(include=["scry_cli*"]),
    package_data={"scry_cli": ["data/*.json"]},
    include_package_data=True,
    python_requires=">=3.9",
    entry_points={
        "console_scripts": [
            "scry = scry_cli.cli:main",
            "scryfall = scry_cli.cli:main",
        ],
    },
)
