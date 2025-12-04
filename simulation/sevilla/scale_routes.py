#!/usr/bin/env python3
import sys
import pandas as pd

def main(input_path, output_path, scale_factor):
    # Read CSV file (first row is the header)
    df = pd.read_csv(input_path)

    # Scale all columns except the first one (label, e.g. "RUTAS")
    # and the last one (total), using the given scale_factor
    if df.shape[1] < 3:
        raise ValueError("Expected at least 3 columns: label, some values, and a total column.")

    # All numeric data columns, excluding first (index 0) and last (index -1)
    data_cols = df.columns[1:-1]

    # Apply scaling and round to nearest integer
    df.loc[:, data_cols] = (df.loc[:, data_cols] * scale_factor).round().astype(int)

    # Recalculate the last column as the row-wise sum of all scaled data columns
    total_col = df.columns[-1]
    df[total_col] = df.loc[:, data_cols].sum(axis=1)

    # Save the resulting DataFrame to CSV without index
    df.to_csv(output_path, index=False)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} input.csv output.csv scale_factor")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    scale_factor = float(sys.argv[3])

    main(input_path, output_path, scale_factor)
