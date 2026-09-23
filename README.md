# Introduction

This component has been created to be used with Home Assistant.

Mazda 6e presents a possibility to connect your Mazda 6e vehicle to Home Assistant.
This integration accepts your email and password and encrypts them internally. A device ID is generated automatically and retained for reauthentication. Enter the verification code sent by email when requested. Plaintext credentials and passwords are not saved in the config entry.

The integration exposes a lock entity for the vehicle doors. Mazda's six-digit Control Passcode can be entered during setup or later through **Reconfigure**. The lock entity remains unavailable until the passcode and control key have been configured. Normal Home Assistant lock and unlock actions do not ask for a code.

This is the **extended** build. It uses the domain `mazda_6e_extended`, so it can be
installed and configured next to the original `mazda_6e` integration without conflicts.
Use a **separate device ID** during setup, otherwise both instances fight over the same
session on the Mazda backend.

# Extended features

In addition to the upstream integration's vehicle data, this build provides:

- A GPS `device_tracker` for the vehicle's last reported location.
- Sensors for speed, AC and DC charging current, charge target, cockpit and target
	temperature, cabin PM2.5, power state, vehicle status, and last update time.
- Binary sensors for the driver and passenger locks, DC charging connection, air
	conditioning, defrost, steering-wheel heating, and vehicle connectivity.
- Seat-status and tire-pressure entities, plus door and window state for every seating
	position.
- More resilient vehicle and status retrieval, including location data and additional
	Mazda vehicle-data fields.
- A **Reconfigure** flow to update account credentials and the Control Passcode without
	removing the integration.

# Cloud controls

All cloud controls require the control key registered during sign-in. Available controls
depend on the vehicle capabilities Mazda advertises:

- Door lock and unlock require Mazda's six-digit Control Passcode.
- Windows and trunk are exposed as Home Assistant covers and require the Control Passcode.
- Cabin climate provides on/off control and a target temperature. The captured Mazda request
	does not require the Control Passcode.
- **Find vehicle** triggers Mazda's flashing-and-honking command and does not require the
	Control Passcode.
- **Honk horn** triggers Mazda's captured horn command and does not require the Control
	Passcode.

The GPS tracker and speed sensor are created only when Mazda returns valid coordinates or
speed in the vehicle status payload.

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

`Note`: If installing manually, in order to be alerted about new releases, you will need to subscribe to releases from this repository

# Cloud-control passcode

The Control Passcode is required by Mazda for cloud vehicle controls. Bluetooth control in the Mazda app does not request it, so disable Bluetooth on the phone or move outside Bluetooth range before looking for the prompt:

1. Open the Mazda app with Bluetooth disabled or while outside Bluetooth range of the vehicle.
2. Start a cloud vehicle-control action, such as locking or unlocking the doors.
3. Enter the requested six-digit Control Passcode. If it is unknown, use **Forgot PWD** in the Mazda app to reset it.
4. In Home Assistant, open the Mazda 6e integration and select **Reconfigure**.
5. Enter the Mazda account credentials and the same six-digit Control Passcode.

Reconfiguration signs in again and registers the control key required for signed cloud commands. The passcode is stored in the Home Assistant config entry as an integration credential. It is encrypted before being sent to Mazda and is never exposed as a code field on the lock entity.
