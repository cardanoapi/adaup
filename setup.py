from setuptools import setup, find_packages
import os

setup(
    name='adaup',
    version='0.1.5',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
        'tqdm',
    ],
    entry_points={
        'console_scripts': [
            'cardano=adaup:main',
        ],
    },
    author='Sudip Bhattarai',
    author_email='sudip@bhattarai.me',
    description='A Python package for interacting with Cardano.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/dquadrant/kuber',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
