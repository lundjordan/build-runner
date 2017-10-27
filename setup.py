# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from setuptools import setup

setup(
    name="runner",
    version="2.1",
    description="Task runner",
    author="Chris AtLee",
    author_email="chris@atlee.ca",
    packages=[
        "runner",
        "runner.lib"
    ],
    entry_points={
        "console_scripts": ["runner = runner:main"],
    },
    url="https://github.com/mozilla/runner",
)
