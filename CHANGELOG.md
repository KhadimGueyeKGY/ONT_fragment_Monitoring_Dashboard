# Changelog

## 3.0.2

- The dashboard window opens full screen (maximized) at every start. It can still be made
  smaller; windows that are already open are not changed.

## 3.0.1

- Faster: the statistics of a barcode are computed about 25 times faster (same values).
- Barcodes are processed 5 at a time (setting: Barcodes processed at the same time).
- Each barcode appears in the charts as soon as it is finished, without waiting for the
  others.
- The analysis uses half of the processors by default and runs at low priority, so the
  sequencing software is not slowed down.
- Windows: "Malaria dashboard monitor" program with the logo, no console window, an icon
  near the clock, and a shortcut on the Desktop and in the Start menu.
- macOS and Linux: "Malaria dashboard monitor" application with the logo, added at the
  first start.
- The dashboard opens in its own window (Edge or Chrome app window).
- The update check runs at every start and its window comes first.
- A barcode that fails no longer stops the monitoring: it is tried again at the next check.
- Explorer style folder window on Windows.
- Plate map tab: one 96-well plate per fragment, barcode01 in A1 then down each column.
- On tablets and phones the run setup folds away once results are shown.
- Clear message when the dashboard is closed, and the page reconnects by itself.

## 3.0.0

- Starts with a double-click on Windows, macOS and Linux. conda, the environment, the
  reference and its index are checked and installed automatically.
- New fragment catalog: IGH panel plus the NOMADS8, NOMADS16 and NOMADS-MVP panels, grouped
  by category or by panel. Positions can be changed and custom fragments added.
- Reads are mapped on the selected fragments only, and only new files are processed.
- New views: overview heatmap, plate map per fragment, reads per fragment, depth and coverage,
  hrp2 / hrp3 screen.
- Paths are understood in any format (Windows, WSL, macOS, Linux). Native folder picker.
- Update check with a short dialog.
- Works on large screens, laptops and phones, light and dark theme.

## 2.0.0

- Notebook dashboard run with Voila.
