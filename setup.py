from setuptools import find_packages, setup
from os.path import abspath, dirname, join

setup(
    name="tap-nice-incontact",
    version="0.1.2",
    description="Singer.io tap for extracting data from the NICE InContact Reporting API",
    author="Stitch",
    url="http://singer.io",
    classifiers=["Programming Language :: Python :: 3 :: Only"],
    py_modules=["tap_nice_incontact"],
    install_requires=[
        "backoff==1.8.0",
        "certifi==2020.12.5",
        "chardet==4.0.0",
        "ciso8601==2.1.3",
        "idna==2.10",
        "jsonschema==2.6.0",
        "python-dateutil==2.8.1",
        "pytz==2018.4",
        "requests==2.25.1",
        "simplejson==3.11.1",
        "singer-python==5.12.1",
        "six==1.15.0",
        "urllib3==1.26.6",
        "isodate==0.6.0",
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
