from setuptools import find_packages, setup
from os.path import abspath, dirname, join

ROOT_DIR = abspath(dirname(__file__))

with open(join(ROOT_DIR, "README.md"), encoding="utf-8") as f:
    readme = f.read()

setup(
    name="tap-nice-incontact",
    version="0.1.0",
    description="Singer.io tap for extracting data from the NICE InContact Reporting API",
    long_description=readme,
    author="Stitch",
    url="http://singer.io",
    classifiers=["Programming Language :: Python :: 3 :: Only"],
    py_modules=["tap_nice_incontact"],
    install_requires=[
        "backoff==1.8.0",
        "requests==2.25.1",
        "singer-python==5.12.1",
        "isodate==0.6.0"
    ],
    entry_points="""
    [console_scripts]
    tap-nice-incontact=tap_nice_incontact:main
    """,
    packages=find_packages(exclude=["tests"]),
    package_data = {
        "schemas": ["tap_nice_incontact/schemas/*.json"]
    },
    include_package_data=True,
)
