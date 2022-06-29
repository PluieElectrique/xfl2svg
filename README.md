# xfl2svg

Convert Adobe Animate XFL to SVG.

## Install

You will need Python 3.7+ (tested on 3.9). Currently, installation requires building from source, so first install [Flit](https://flit.readthedocs.io/) with:

```
$ python3 -m pip install flit
```

Then, run either of:

```
$ pip install  .
$ pip install '.[tqdm]'   # If you want a progress bar
```

## Usage

You will need an XFL project (tested with Animate 2022), either in compressed `.fla` form or as a decompressed directory. To convert all frames of "Scene 1" to SVG, run:

```
$ xfl2svg [path to .fla or dir] "Scene 1" [output dir]
```

You can change the frames rendered, SVG height and width, indent the SVG (Python 3.9+), etc. For example, this will render the first 5 frames of a symbol, centered in the viewport, with no background:

```
$ xfl2svg [path] "Symbol 1" [outdir] --last-frame 5 --center --no-background
```

Use `xfl2svg -h` to see all the options.

## Limitations

This is a work in progress. Many XFL features are not supported (e.g. tweens, radial gradient) or do not work correctly. Use of these features may cause glitches in the output (e.g. stuttering, missing colors) or even crashes.

Other than that, the generated SVG should look similar to Animate's. It may not be identical, though, as Animate sometimes rounds coordinates by a few tenths of a pixel. It's not clear exactly why or when this is done, so it can't be replicated, but luckily, it's not very noticeable.

Finally, for convenience, `xfl2svg` makes no attempt to copy the structure of Animate's SVG. That is, the generated SVG has different whitespace, element IDs, element ordering, etc. compared to Animate. This should not affect the visual result.

## How does it work?

There is no official documentation for XFL, so everything was discovered through experimentation and the few resources available:

* [SasQ's XFL notes](https://github.com/SasQ/SavageFlask/blob/master/doc/FLA.txt)
* [Explanation of the XFL edge format on StackOverflow](https://stackoverflow.com/a/4077709)

This project has no documentation of XFL either, but the code hopefully serves as a substitute. In particular, [`shape/edge.py`](https://github.com/PluieElectrique/xfl2svg/blob/master/xfl2svg/shape/edge.py) is densely commented and explains how shapes and strokes are converted from XFL to SVG.

For reference, here is an overview of the code:

* `__main__.py`: Command-line interface
* `xfl_reader.py`: Reads and preprocesses an XFL project. Provides timeline data to `SvgRenderer`.
* `svg_renderer.py`: Recursively renders XFL to SVG. Uses `shape` for `<DOMShape>` and `color_effect` for effects on symbols.
* `shape/`:
  * `shape.py`: Converts `<DOMShape>` to SVG. Uses `edge` for shapes/strokes and `style` for styles.
  * `edge.py`: Parses the XFL edge format and builds shapes/strokes.
  * `style.py`: Parses fill and stroke styles used by `<DOMShape>`.
  * `gradient.py`: Parses gradient fills.
* `color_effect.py`: Parses color effects (e.g. brightness, tint, alpha) used on symbols.
* `util.py`: Utility functions.

Also, XFL is closely related to Flash/SWF, so resources like the [SWF file format specification](https://archive.org/details/swf-file-format-spec/mode/2up) and [Ruffle's source code](https://github.com/ruffle-rs/ruffle) may be useful.

## Legal

This program is licensed under the MIT License. See the `LICENSE` file for more information.
