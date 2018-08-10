#!/bin/bash
if [ -d "build" ]; then
    rm -rf build
fi 

virtualenv venv
source venv/bin/activate

pip install -r requirements.txt

python3 -m pytest --cov=tagger --cov-report html:cov_html

deactivate

mkdir build
find . | grep -E "(__pycache__|\.pyc|\.pyo)" | xargs rm -rf
cp -r tagger build

find ./venv/lib/python3.6/site-packages/ | grep -E "(moto|mock|pytest|pytest_cov|coverage)" | xargs rm -rf
cp -r venv/lib/python3.6/site-packages/* build/

cd build 
#zip -r LUAUTagger.zip .
cd ..
#mv build/LUAUTagger.zip ./LUAUTagger.zip

rm -rf venv
rm -rf build
find . | grep -E "(.pytest_cache|__pycache__|\.pyc|\.pyo)" | xargs rm -rf