# ONT Fragment Monitoring Dashboard

Real-time monitoring of Oxford Nanopore amplicon sequencing for *Plasmodium falciparum*.
While MinKNOW is writing reads, the dashboard maps them on the fragments you choose and
shows, for every barcode, how many reads each fragment has received, the depth and the
coverage along each fragment, and an hrp2 / hrp3 screen when those genes are selected.

It stops at the BAM stage. It does not call variants. Its only purpose is to tell the
lab whether each barcode and fragment has enough reads, so sequencing can be stopped at
the right time.

Author: Khadim Gueye, Malaria team, Institute of Genomics and Global Health (IGH).

## 1. Start the dashboard

Double-click the launcher for your computer. Nothing else is needed.

| Computer | Double-click |
|---|---|
| Windows | `Start_Dashboard_Windows.bat` |
| macOS | `Start_Dashboard_macOS.command` |
| Linux | `Start_Dashboard_Linux.sh` |

A small window opens and the dashboard appears in your web browser. Keep the small
window open while you use the dashboard. To close everything, use **Close the dashboard**
in the menu (three dots, top right), or close the small window.

The first start takes a few minutes, because the launcher prepares everything by itself:

1. It looks for conda. If there is none, it downloads and installs Miniforge (a free
   conda distribution) in your home folder.
2. It creates the software environment `ont_fragment_dashboard` (minimap2, samtools,
   pysam), or updates it when `environment.yml` has changed.
3. The dashboard checks the reference genome `Reference/Pf3D7_v2.fasta` and its index.
   If they are missing, it downloads the Pf3D7 genome (PlasmoDB release 54, from the
   MalariaGEN Pf8 resource) and indexes it.

A window then confirms that everything is ready.

### Windows

The analysis tools (minimap2, samtools) only exist for Linux and macOS, so on Windows the
dashboard runs inside WSL (Windows Subsystem for Linux). If WSL is not installed, the
launcher offers to install it. This needs administrator rights and a restart, once.

### macOS

The first time, macOS may refuse to open a file downloaded from the internet. Right-click
`Start_Dashboard_macOS.command`, choose **Open**, then confirm.

### Linux

If double-clicking opens the file in a text editor, right-click it, open **Properties**,
allow it to run as a program, or start it from a terminal with
`bash Start_Dashboard_Linux.sh`.

## 2. Monitor a run

1. **Sequencing run.** Click **Browse** and choose the `fastq_pass` folder, or the run
   folder that contains it. You can also paste a path. Any format is understood:
   `C:\data\run1\fastq_pass`, `/mnt/c/data/run1/fastq_pass`, `\\wsl.localhost\Ubuntu\home\...`,
   `/Users/name/run1` or `/data/run1`. If the native folder window does not open, use
   **Browse here**, which browses folders inside the dashboard.
2. **Fragments.** Tick the fragments to monitor. They can be grouped by category (Drug
   resistance, Diversity, Diagnostic, Vaccine) or by panel (IGH, NOMADS8, NOMADS16,
   NOMADS-MVP). Use the pencil to change the position of a fragment, and **+ Custom** to
   add your own fragments, one by one or from a BED or TSV file.
3. **Settings** (optional). Reads needed per fragment (default 100), depth counted as
   covered, minimum mapping quality, minimum part of the fragment a read must cover,
   time between two checks, CPU threads.
4. Click **Start monitoring**. New reads are processed automatically every 30 seconds.
   Click **Stop monitoring** to stop. Starting again on the same run continues where it
   stopped: files already processed are not processed again.

## 3. Read the results

| Tab | What it shows |
|---|---|
| Overview | One cell per barcode and fragment with its read count. Blue: target reached. Red: below target, darker means fewer reads. Click a cell to open the fragment. |
| Plate map | One 96-well plate per fragment. Blue: target reached. Red: below target. Grey: 0 reads. Dashed: no barcode in that well. The layout is fixed by the lab, not read from the run: barcode01 in A1, then down each column (barcode02 in B1 ... barcode08 in H1, barcode09 in A2). |
| Reads per fragment | One bar chart per fragment, one bar per barcode, with the target as a dashed line. |
| Depth and coverage | Mean depth and percentage of the fragment covered, then the depth along a fragment for each barcode. |
| hrp2 / hrp3 | Shown only when hrp2 or hrp3 is selected. Status per barcode, and reads on hrp2 / hrp3 compared with the other fragments. |
| Activity | What the dashboard is doing, and a download of the full fragment table. |

### hrp2 and hrp3 screen

This screen is a monitoring help, not a deletion call. The rules are a convention of this
dashboard and are not taken from a published method:

- **Detected**: the gene has at least the target number of reads.
- **Possible deletion**: the median of the other selected fragments of the barcode reached
  the target, while the gene has less than 5 percent of that median.
- **Below target**: the other fragments reached the target and the gene has reads, but
  fewer than the target.
- **Not enough data**: the other fragments have not reached the target yet.

Confirm any possible deletion with the validated method of the lab. Because hrp2 and hrp3
reads align to each other, when only one of the two genes is selected the other one is
added to the mapping reference (it is not displayed) so that its reads are not counted on
the monitored gene.

## 4. How reads are counted

1. The selected fragments are extracted from the Pf3D7 genome (with 50 bases on each
   side, overlapping fragments merged into one locus). Reads are mapped on these loci only,
   not on the whole genome, which is faster and fits amplicon sequencing.
2. Only new FASTQ files of each barcode are mapped (`minimap2 -ax map-ont`), then merged
   into one sorted and indexed BAM per barcode.
3. A read counts for a fragment when it is a primary alignment, its mapping quality is at
   least the minimum (default 10), and it covers at least the chosen part of the fragment
   (default 50 percent). A long read that spans two overlapping fragments counts for both.
4. Depth is computed with the same filters. Coverage is the percentage of bases of the
   fragment with a depth at least equal to the chosen value (default 10).

The target of 100 reads per fragment is a choice of the lab, not a published standard.
It can be changed in the settings.

## 5. Output files

Each run is written in `results/<run folder name>_<code>/`. The button **Results folder**
opens it.

| File | Content |
|---|---|
| `bam/barcodeXX.bam` and `.bai` | reads of the barcode aligned on the selected fragments |
| `fragment_stats.tsv` | barcode, fragment, reads, mean depth, coverage |
| `hrp_deletion_screen.tsv` | hrp2 / hrp3 status per barcode, when selected |
| `fragments_reference.fasta` | the extracted loci used for mapping |
| `run_info.json` | run folder, fragments and settings used |
| `results.json`, `state.json` | what the dashboard displays, and the files already processed |

## 6. Fragment catalog

All fragments are listed in `panels/fragments.tsv` (1-based coordinates on Pf3D7). Their
origin is described in `panels/SOURCES.md`:

- **IGH**: the amplicons of the IGH malaria team.
- **NOMADS8, NOMADS16, NOMADS-MVP**: the amplicon panels of the `nomadic` software
  (github.com/JasonAHendry/nomadic).

Fragments you add, and positions you change, are kept in `panels/custom.tsv`. Use
**Restore default position** in the edit window to undo a change.

## 7. Updates

At each start the dashboard checks whether a newer version is published on GitHub. If
there is one, a window asks whether to update now or later. Updating keeps your results,
the reference genome and your custom fragments, then restarts the dashboard.

## 8. Troubleshooting

| Problem | What to do |
|---|---|
| The browser did not open | Open the address shown in the small window, for example `http://127.0.0.1:8866`. |
| "No fastq_pass folder" | Select the `fastq_pass` folder itself or a folder above it. |
| A barcode stays at 0 | Check that its folder contains `.fastq` or `.fastq.gz` files. Files are processed about 10 seconds after they are written. |
| The reference download fails | Check the internet connection, then close and start the dashboard again. |
| Something else | Read the **Activity** tab and the small window. |

Reproducibility: the software versions are those of the conda environment
`ont_fragment_dashboard` defined in `environment.yml` (Python, minimap2, samtools, pysam,
numpy, plotly).
