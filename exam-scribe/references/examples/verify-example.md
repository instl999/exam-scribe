<!-- EXAMPLE of a finished claim-check worksheet. Three items were planted false claims (1010 J, 'outside matter', 'kinetic calorie'). -->
# Claim check — ch01 batch 01
<!-- ROLE: independent checker. Judge each claim ONLY by its context line (text copied from the book). -->
<!-- verdict: SUPPORTED = the context clearly says this (numbers, signs and conditions included)
              PARTIAL = partly right, a condition/qualifier is missing or changed, or the claim adds something
                        the context does not say (a reason, a contrast, a wider scope)
              NOT_SUPPORTED = the context does not say this
              CONTRADICTED = the context says the opposite -->
<!-- span: for SUPPORTED, copy the exact supporting words from the context (at least 3 words). Otherwise NONE. -->
<!-- problem: if not SUPPORTED, one sentence saying what is wrong. -->
<!-- Some claims are deliberately false to test attention. Check every word. Do not edit claim: or context: lines. -->

::: claim V-0679e4d9
claim: doubling the speed multiplies the kinetic energy by four, because the speed is squared.
context: [p.1] where m is the mass of the object in kilograms and v is its speed in meters per second. Because the speed is squared, doubling the speed of an object multiplies its kinetic energy by four.
verdict: SUPPORTED
span: doubling the speed of an object multiplies its kinetic energy by four

:::

::: claim V-1a9fc2e1
claim: The book defines "Law of conservation of energy" as: "Energy can be converted from one form to another, but it is never created or destroyed. This principle is called the law of conservation of energy."
context: [p.2] Energy can be converted from one form to another, but it is never created or destroyed. This principle is called the law of conservation of energy.
verdict: SUPPORTED
span: This principle is called the law of conservation of energy

:::

::: claim V-70a11066
claim: Anything that moves has kinetic energy; more mass or more speed means more kinetic energy.
context: [p.1] Kinetic energy is the energy that an object possesses because of its motion. A rolling ball, a flowing river, and a vibrating molecule all have kinetic energy. The kinetic energy of an object depends on both its mass and its speed:
verdict: PARTIAL
span: NONE
problem: The context says kinetic energy depends on mass and speed but does not say that more mass or speed gives more kinetic energy.
:::

::: claim V-f0e49ce2
claim: energy only changes form; it is never created or destroyed.
context: [p.2] Energy can be converted from one form to another, but it is never created or destroyed. This principle is called the law of conservation of energy.
verdict: SUPPORTED
span: it is never created or destroyed

:::

::: claim V-124cb136
claim: The joule (J) is the SI unit of energy, and 1 kJ = 1010 J.
context: [p.3] The SI unit of energy is the joule (J). One joule is the kinetic energy of a 2-kg object moving at a speed of 1 meter per second. A joule is a small amount of energy, so chemists often report energies in kilojoules (kJ); 1 kJ = 1000 J. … [p.3] The SI unit of energy is the joule (J). One joule is the kinetic energy of a 2-kg object moving at a speed of 1 meter per second. A joule is a small amount of energy, so chemists often report energies in kilojoules (kJ); 1 kJ = 1000 J.
verdict: CONTRADICTED
span: NONE
problem: The context says 1 kJ = 1000 J, not 1010 J.
:::

::: claim V-4e34fc97
claim: The book defines "Potential energy" as: "Potential energy is the energy that an object possesses because of its position, composition, or condition."
context: [p.2] Potential energy is the energy that an object possesses because of its position, composition, or condition. A ball held above the ground has gravitational potential energy, and a battery stores chemical potential energy in the arrangement of its atoms.
verdict: SUPPORTED
span: Potential energy is the energy that an object possesses

:::

::: claim V-89c592d0
claim: Thermal energy — What moves: the atoms and molecules outside matter, at random
context: [p.2] The atoms and molecules in any sample of matter are in constant random motion. Thermal energy is the kinetic energy associated with the random motion of these particles. A cup of hot tea has more thermal energy than the same cup of tea after it has cooled, because its molecules move faster on average.
verdict: CONTRADICTED
span: NONE
problem: The context says the atoms and molecules are in matter (in any sample of matter), not outside it.
:::

::: claim V-e18547c7
claim: A ball held above the ground has gravitational potential energy, and a battery stores chemical potential energy.
context: [p.2] Potential energy is the energy that an object possesses because of its position, composition, or condition. A ball held above the ground has gravitational potential energy, and a battery stores chemical potential energy in the arrangement of its atoms.
verdict: SUPPORTED
span: a battery stores chemical potential energy

:::

::: claim V-4c1bde49
claim: KE = kinetic energy; m = mass of the object (kg); v = its speed (m/s).
context: [p.1] where m is the mass of the object in kilograms and v is its speed in meters per second. Because the speed is squared, doubling the speed of an object multiplies its kinetic energy by four.
verdict: SUPPORTED
span: m is the mass of the object in kilograms and v is its speed in meters per second

:::

::: claim V-0bb6552c
claim: Energy is what lets something heat another object or do work, and work means pushing matter over a distance.
context: [p.1] Chemical changes and physical changes are almost always accompanied by changes in energy. Energy is the capacity to supply heat or do work. Work is done when a force moves matter through a distance. Energy exists in many forms, but most of them can be grouped into two broad classes.
verdict: SUPPORTED
span: Work is done when a force moves matter through a distance

:::

::: claim V-acc66cb5
claim: The book defines "Kinetic energy" as: "Kinetic energy is the energy that an object possesses because of its motion."
context: [p.1] Kinetic energy is the energy that an object possesses because of its motion. A rolling ball, a flowing river, and a vibrating molecule all have kinetic energy. The kinetic energy of an object depends on both its mass and its speed:
verdict: SUPPORTED
span: Kinetic energy is the energy that an object possesses because of its motion

:::

::: claim V-e89aaaa3
claim: The book defines kinetic calorie by motion and potential energy by position, composition, or condition.
context: [p.1] Kinetic energy is the energy that an object possesses because of its motion. A rolling ball, a flowing river, and a vibrating molecule all have kinetic energy. The kinetic energy of an object depends on both its mass and its speed: … [p.2] Potential energy is the energy that an object possesses because of its position, composition, or condition. A ball held above the ground has gravitational potential energy, and a battery stores chemical potential energy in the arrangement of its atoms.
verdict: NOT_SUPPORTED
span: NONE
problem: The context defines kinetic energy by motion; it says nothing about a kinetic calorie.
:::

::: claim V-efe4a44f
claim: The book defines "Energy" as: "Energy is the capacity to supply heat or do work."
context: [p.1] Chemical changes and physical changes are almost always accompanied by changes in energy. Energy is the capacity to supply heat or do work. Work is done when a force moves matter through a distance. Energy exists in many forms, but most of them can be grouped into two broad classes.
verdict: SUPPORTED
span: Energy is the capacity to supply heat or do work

:::

::: claim V-d38acd9e
claim: Nearly every chemical or physical change comes with a change in energy.
context: [p.1] Chemical changes and physical changes are almost always accompanied by changes in energy. Energy is the capacity to supply heat or do work. Work is done when a force moves matter through a distance. Energy exists in many forms, but most of them can be grouped into two broad classes.
verdict: SUPPORTED
span: almost always accompanied by changes in energy

:::

::: claim V-490baaa2
claim: Potential energy is stored energy that comes from where an object is or what it is made of.
context: [p.2] Potential energy is the energy that an object possesses because of its position, composition, or condition. A ball held above the ground has gravitational potential energy, and a battery stores chemical potential energy in the arrangement of its atoms.
verdict: PARTIAL
span: NONE
problem: The claim leaves out 'condition': the context says position, composition, or condition.
:::
