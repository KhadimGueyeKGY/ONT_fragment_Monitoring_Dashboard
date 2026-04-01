# ONT Fragment Monitoring Dashboard

This package provides a Voilà-ready dashboard for real-time ONT fragment monitoring during sequencing.

It implements the workflow requested in your specification, with a fixed reference path and a single user input for the `fastq_pass` directory. fileciteturn3file0

## What the dashboard does

- asks the user only for the path to `fastq_pass`
- uses a fixed reference path: `Reference/Pf3D7_v2.fasta`
- aligns reads with `minimap2`
- sorts and indexes BAM files with `samtools`
- counts reads per barcode and per fragment
- stores BAM outputs in `/tmp/ont_fragment_dashboard/run`
- stores tables, logs, and status files in `/tmp/ont_fragment_dashboard/res`
- refreshes automatically every 60 seconds by default
- runs in the browser through Voilà
- shows two tabs:
  - `Tables`
  - `Figures`

## Package contents

- `ONT_Fragment_Monitoring_Dashboard.ipynb`
- `README.md`
- `environment.yml`
- `launch_dashboard.sh`

## Expected folder layout

Put the package files in a working directory and create a `Reference` folder next to the notebook:

```bash
project_root/
├── ONT_Fragment_Monitoring_Dashboard.ipynb
├── README.md
├── environment.yml
├── launch_dashboard.sh
└── Reference/
    └── Pf3D7_v2.fasta
```

## Create the environment

```bash 
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
conda install -n base -c conda-forge mamba

```

Using Mamba:

```bash
mamba env create -f environment.yml
conda activate ont_fragment_dashboard
```

Using Conda:

```bash
conda env create -f environment.yml
conda activate ont_fragment_dashboard
```

## Download the reference

Create the reference directory:

```bash
mkdir -p Reference
```

Download the FASTA:

```bash
wget -O Reference/Pf3D7_v2.fasta "https://pf8-release.cog.sanger.ac.uk/reference/PlasmoDB-54-Pfalciparum3D7-Genome.fasta"
```

Create the FASTA index:

```bash
samtools faidx Reference/Pf3D7_v2.fasta
```

Optional minimap2 index:

```bash
minimap2 -d Reference/Pf3D7_v2.mmi Reference/Pf3D7_v2.fasta
```

The dashboard uses `Reference/Pf3D7_v2.fasta` directly. The `.mmi` file is optional.

## Launch with Voilà

From the package directory:

```bash
voila ONT_Fragment_Monitoring_Dashboard.ipynb --no-browser --port=8866
```

Then open:

```text
http://127.0.0.1:8866
```

You can also use:

```bash
bash launch_dashboard.sh
```

Or set a custom port:

```bash
bash launch_dashboard.sh 8899
```

## How to use the dashboard

1. Launch Voilà.
2. Open the browser URL.
3. Enter the full path to the `fastq_pass` directory.
4. Choose refresh interval and threads.
5. Click `Run monitoring`.

After that, the dashboard updates automatically. The user does not need to click `Run monitoring` again.

## Output locations

### BAM and temporary read files

```text
/tmp/ont_fragment_dashboard/run
```

Contains:
- concatenated FASTQ files per barcode
- BAM files
- BAI files

### Result files

```text
/tmp/ont_fragment_dashboard/res
```

Contains:
- `read_counts.csv`
- `summary.csv`
- `dashboard.log`
- `status.json`

## Dashboard layout

### Tables tab

#### `read_counts`
- rows are barcodes
- columns are fragments
- values are read counts
- values below 100 are red
- values at or above 100 are blue

#### `summary`
- one row per fragment
- `total_samples`
- `pass_samples`
- `pass_percentage`

### Figures tab

- one Plotly bar chart per fragment
- x-axis = barcode
- y-axis = read count
- red bars = below 100
- blue bars = at or above 100
- dashed red horizontal line at 100
- figures are shown two per row

### Monitoring and status

The dashboard also shows:
- current run status
- backend spinner
- live metrics
- rolling backend log
- a sequencing recommendation based on current pass counts

## Important behavior

This dashboard intentionally stops at the BAM stage.
It does not generate VCF files or perform downstream variant analysis.

Its goal is to help biologists monitor whether each barcode and fragment has reached the required number of reads during sequencing.

## Troubleshooting

### Missing tools

Check:

```bash
which minimap2
which samtools
which voila
```

### Missing reference

Make sure this file exists:

```text
Reference/Pf3D7_v2.fasta
```

### No barcodes found

The dashboard input must point directly to the `fastq_pass` directory, not its parent.

Correct:

```text
/path/to/run/fastq_pass
```

Incorrect:

```text
/path/to/run
```

