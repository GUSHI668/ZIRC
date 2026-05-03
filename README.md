<!-- README.md -->

<p align="center">
  <img src="docs/pic/zirc.jpg" width="160" height="160" alt="LOGO">
</p>
<h1 align="center">ZIRC's IL2CPP Reverse Collapse</h1>

This repo show reverse engineering of game "Girls' Frontline", including auto farm, dragging and so on. Most of its functions are based on the reverse `AuthCode` for encrypting and decrypting the payload, while a small portion are derived from `Frida` or `Minhook`.

## 1. Architecture

In short, this repo's directory tree can be listed as:

```sh
.
├── docs                  # Documents
├── poc                   # Proof of Concept
├── src                   # Source
│   ├── core                # PyPI lib
│   │   └── gflzirc
│   ├── demo                # Sample of gflzirc
│   ├── gha                 # Run demo on GHA
│   └── trimmer           # Implementation of PoC (deprecated)
└── tools
```

## 2. Reading List

1. [Proof of Concept Lists](docs/00_poc_list.md), delineates the specific functionalities encapsulated within the `poc/` directory.
2. [Implementation of Poc via Minhook](docs/01_trimmer.md), TODO.
3. [Demystifying gflzirc](docs/02_gflzirc.md), shown the architecture and core functions of `gflzirc`.
4. [Sample of gflzirc](docs/03_demo.md), TODO.
5. [GHA's Design](docs/04_gha.md), shown the mechanic of `src/gha`.