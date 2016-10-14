#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# ezIBpy: Pythonic Wrapper for IbPy
# https://github.com/ranaroussi/ezibpy

"""ezIBpy: Pythonic Wrapper for IbPy
ezIBpy is a Pythonic wrapper for IbPy library
(https://github.com/blampe/IbPy), that was developed to
speed up the development of trading software that relies on
Interactive Brokers for market data and order execution.
"""

from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='ezIBpy',
    version="1.12.22",
    description='Pythonic Wrapper for IbPy',
    long_description=long_description,
    url='https://github.com/ranaroussi/ezibpy',
    author='Ran Aroussi',
    author_email='ran@aroussi.com',
    license='LGPL',
    classifiers=[
        'License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)',
        'Development Status :: 5 - Production/Stable',

        'Operating System :: OS Independent',
        'Intended Audience :: Developers',
        'Topic :: Office/Business :: Financial',
        'Topic :: Office/Business :: Financial :: Investment',
        'Topic :: Scientific/Engineering :: Interface Engine/Protocol Translator',
        'Topic :: Software Development :: Libraries',
        'Topic :: Software Development :: Libraries :: Python Modules',

        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    platforms = ['any'],
    keywords='ezibpy interactive brokers tws, ibgw, ibpy',
    packages=find_packages(exclude=['contrib', 'docs', 'tests', 'examples']),
    install_requires=['pandas'],
    entry_points={
        'console_scripts': [
            'sample=sample:main',
        ],
    },
)