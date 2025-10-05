from pathlib import Path

import setuptools
from setuptools import setup

this_dir = Path(__file__).parent
module_dir = this_dir / "wyoming_azure_keyword"

requirements = []
requirements_path = this_dir / "requirements.txt"
if requirements_path.is_file():
    with open(requirements_path, encoding="utf-8") as requirements_file:
        requirements = requirements_file.read().splitlines()

data_files = [module_dir / "languages.json"]

# -----------------------------------------------------------------------------

setup(
    name="wyoming_azure_keyword",
    version="1.0.0",
    description="Wyoming Server for Microsoft Azure Keyword detection",
    url="https://github.com/jamescohen/wyoming-azure-keyword",
    author="James Cohen",
    author_email="contact@jamescohen.com",
    license="MIT",
    packages=setuptools.find_packages(),
    package_data={
        "wyoming_azure_keyword": [str(p.relative_to(module_dir)) for p in data_files]
    },
    install_requires=requirements,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Text Processing :: Linguistic",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    keywords="rhasspy wyoming azure keyword",
)