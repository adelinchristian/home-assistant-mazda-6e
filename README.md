# Introduction

This component has been created to be used with Home Assistant.

Mazda 6e presents a possibility to connect your Mazda 6e vehicle to Home Assistant.
Currently, the integration need the **encrypted** email and password from the official app to connect to Mazda API.
An optional **encrypted security code** can now also be stored in the integration options. This is required for some remote-control APIs, but control entities are still blocked until request-signing details are fully implemented.

This is the **extended** build. It uses the domain `mazda_6e_extended`, so it can be
installed and configured next to the original `mazda_6e` integration without conflicts.
Use a **separate device ID** during setup, otherwise both instances fight over the same
session on the Mazda backend.

## Security-code helper services

Two helper services are available for debugging control prerequisites:

- `mazda_6e_extended.security_code_status`
- `mazda_6e_extended.validate_security_code`

Both accept optional `vehicle_id` (integer). If omitted, they run for all configured vehicles
and emit result events on the Home Assistant event bus:

- `mazda_6e_extended_security_code_status`
- `mazda_6e_extended_validate_security_code`

## Control framework status

The API client now includes a control-command skeleton:

- serial number request
- optional encrypted security-code check (`rcToken` path)
- pluggable `sign` hook
- command submit + async result polling

Important: commands still require the real signing algorithm. Without registering a signer,
control submission will raise a signing error by design.

### Experimental signer adapter

An opt-in experimental signer adapter is available in integration options.

Options fields:

- `enable_experimental_signer`
- `command_signer_mode` (currently: `rsa_pkcs1v15_sha256`)
- `command_signer_private_key_pem`

If enabled, the integration builds a canonical `key=value` payload string sorted by key,
then signs it with RSA PKCS1v15 + SHA-256 and base64-encodes the signature.

This is intentionally experimental: Changan-family apps vary by region/version, so payload
fields, canonicalization, and required omitted keys may still differ.

An experimental lock entity is now included and wired to this command framework. Default
function codes are `doorLock` / `doorUnlock` and may need adjustment if your API traffic
uses different values.

An experimental cabin climate entity is also included. It uses default function codes
`airConditioning` / `airConditioningOff` and sends `targetTemp` in deci-degrees Celsius
(e.g. 21.5°C -> `215`). These values may require adjustment for your regional app/backend.

Experimental button entities are included for flashing lights and horn. They currently use
function code `flashingHonking` with action types `1` (flash lights) and `3` (horn), which
may require tuning for your regional app/backend.

Experimental cover entities are included for windows and trunk. They currently use function
codes `windows` and `trunk` with payload keys modeled after Changan-family APIs
(`open`, `openType`, and `command`), and may require tuning for your regional app/backend.

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
