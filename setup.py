from setuptools import find_packages, setup

requirements_file = "requirements.txt"

with open("README.md") as f:
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
    install_requires=open(requirements_file).readlines(),
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
