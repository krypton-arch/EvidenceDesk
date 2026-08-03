#!/bin/bash
echo "Running Real-Scale Evaluation..."
cd backend/scripts
python generate_evaluation_dataset.py
python evaluate_real_scale.py
echo "Generating Profiling Graph..."
python generate_profiling_graph.py
cd ../..
echo "Reproducibility package finished."
