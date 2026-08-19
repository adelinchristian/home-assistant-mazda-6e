# Introduction

This component has been created to be used with Home Assistant.

Mazda 6e presents a possibility to connect your Mazda 6e vehicle to Home Assistant.
Currently, the integration need the **encrypted** email and password from the official app to connect to Mazda API.

This is the **extended** build. It uses the domain `mazda_6e_extended`, so it can be
installed and configured next to the original `mazda_6e` integration without conflicts.
Use a **separate device ID** during setup, otherwise both instances fight over the same
session on the Mazda backend.

# Installation

## With HACS

1. Add this repository as a custom repository in HACS.
2. Download the integration.
3. Restart Home Assistant

HACS installs the integration into `custom_components/mazda_6e_extended`, taken from the
`domain` in `manifest.json`, so the source directory name in this repository does not matter.

## Manual

Copy the `mazda_6e` directory, from `custom_components` in this repository, into your Home
Assistant Core installation's `custom_components` directory **and rename it to
`mazda_6e_extended`** so it matches the integration domain. Restart Home Assistant prior to
moving on to the `Setup` section.

`Note`: If installing manually, in order to be alerted about new releases, you will need to subscribe to releases from this repository.
