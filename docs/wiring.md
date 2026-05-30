# DARKMAP-Q Wiring Guide

> CRITICAL: The Arduino UNO Q uses **3.3 V logic** on its JDIGITAL / JANALOG
> headers. It is NOT a 5 V Arduino Uno. Read the HC-SR04 section before wiring
> the ultrasonic sensor or you can damage the board.

## Pin map (matches `arduino/darkmap_rover.ino`)

| Function              | UNO Q pin | Notes                                            |
|-----------------------|-----------|--------------------------------------------------|
| Left motor forward    | D5 (PWM)  | to motor driver IN1                              |
| Left motor reverse    | D6 (PWM)  | to motor driver IN2                              |
| Right motor forward   | D9 (PWM)  | to motor driver IN3                              |
| Right motor reverse   | D10 (PWM) | to motor driver IN4                              |
| Servo signal          | D11 (PWM) | SG90 signal; power servo externally (see below)  |
| Ultrasonic TRIG       | D7        | output; 3.3 V trigger is accepted by HC-SR04     |
| Ultrasonic ECHO       | D8        | input; **must go through a voltage divider**     |
| Common ground         | GND       | shared by UNO Q, motor driver, motor battery     |

> Do **not** use D3 for the ECHO input. D3 is not 5 V tolerant. Verify each pin
> against your specific motor driver board and UNO Q carrier before powering on.

## HC-SR04 ECHO level shifting (required)

The HC-SR04 ECHO pin commonly outputs 5 V. Drop it to ~3.3 V with a divider:

```text
HC-SR04 ECHO ----[ 2 kOhm ]----+---- UNO Q D8 (ECHO input)
                               |
                            [ 1 kOhm ]
                               |
                              GND
```

Alternatively use a logic level shifter module, or a natively 3.3 V ultrasonic
sensor. TRIG can usually be driven directly from a 3.3 V output.

## Power and ground

```text
Motor battery pack  --->  motor driver  --->  DC motors
UNO Q PWM pins      --->  motor driver control pins (D5/D6/D9/D10)
UNO Q GND           --->  motor driver GND
Motor battery GND   --->  motor driver GND        (all grounds common)
```

Rules:

- Do **not** power the DC motors from the UNO Q.
- Do **not** power a stalling/jittering servo from the UNO Q 5 V pin; prefer an
  external 5 V supply for the servo, with a common ground.
- Power the UNO Q from a stable **5 V / 3 A USB-C** source (or battery bank).
- If the board browns out or resets when motors spin, separate the motor power
  from the board power and double-check the common ground.

## Servo power (preferred)

```text
External 5 V supply ---> servo VCC
UNO Q GND           ---> servo GND
UNO Q D11 (PWM)     ---> servo signal
```

## Quick wiring checklist

- [ ] Motor driver control pins on D5/D6/D9/D10
- [ ] Motor battery -> driver -> motors (not from UNO Q)
- [ ] All grounds common
- [ ] HC-SR04 ECHO routed through divider/level shifter (never direct)
- [ ] ECHO not on D3
- [ ] Servo powered externally, common ground
- [ ] UNO Q on stable 5 V / 3 A supply
