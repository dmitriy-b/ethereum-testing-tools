import yaml
import pandas as pd
import argparse

def load_yaml(file_path):
    """Load YAML file."""
    with open(file_path, "r") as file:
        return yaml.safe_load(file)

def compare_yaml_files(file1_path, file2_path):
    """Compare two YAML files and return differences."""
    data1 = load_yaml(file1_path)
    data2 = load_yaml(file2_path)
    
    all_keys = set(data1.keys()).union(set(data2.keys()))
    differences = []
    
    for key in all_keys:
        value1 = data1.get(key, "Not Present")
        value2 = data2.get(key, "Not Present")
        
        if value1 != value2:
            differences.append({"Parameter": key, "File1": value1, "File2": value2})
    
    df_differences = pd.DataFrame(differences)
    df_differences_only = df_differences[df_differences["File1"] != df_differences["File2"]]
    
    return df_differences_only

def dataframe_to_markdown(df, file1_name="File1", file2_name="File2"):
    """Convert DataFrame to Markdown format."""
    markdown = f"# Differences Between `{file1_name}` and `{file2_name}`\n\n"
    markdown += "| Parameter | " + file1_name + " Value | " + file2_name + " Value |\n"
    markdown += "|-----------|-------------|-------------|\n"
    
    for _, row in df.iterrows():
        markdown += f"| {row['Parameter']} | {row['File1']} | {row['File2']} |\n"
    
    return markdown

def save_to_csv(df, output_path="differences.csv"):
    """Save differences to a CSV file."""
    df.to_csv(output_path, index=False)

def main():
    parser = argparse.ArgumentParser(description="Compare two YAML files and output differences.")
    parser.add_argument("file1", help="Path to the first YAML file")
    parser.add_argument("file2", help="Path to the second YAML file")
    parser.add_argument("--output_csv", help="Path to save the differences in CSV format", default="differences.csv")
    parser.add_argument("--output_md", help="Path to save the differences in Markdown format", default="differences.md")
    
    args = parser.parse_args()
    
    df_differences = compare_yaml_files(args.file1, args.file2)
    
    markdown_result = dataframe_to_markdown(df_differences, args.file1, args.file2)
    with open(args.output_md, "w") as md_file:
        md_file.write(markdown_result)
    
    save_to_csv(df_differences, args.output_csv)
    print("Comparison complete. Differences saved to:")
    print(f"- CSV: {args.output_csv}")
    print(f"- Markdown: {args.output_md}")

if __name__ == "__main__":
    main()
