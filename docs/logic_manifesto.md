# TasteData Algorithm Specifications

## 1. Normalization Bounds
- pH: 2.5 (Min) to 5.0 (Max) -> Note: Sourness is (1.0 - normalized_pH)
- Temperature: 0°C to 80°C
- Sweetness (Brix): 0 to 20
- Spiciness (SHU): 0 to 50,000

## 2. Stevens’s Power Law Exponents (Perceived Intensity)
Equation: Perception = (Normalized_Value ^ Exponent)
- Sweetness: 1.3
- Saltiness: 1.4
- Spiciness/Pain: 0.8
- Sourness: 1.1

## 3. Cross-Modal Mapping Matrix
- SWEET: Pink/Yellow | Round Shapes | High Pitch Piano | Legato
- SOUR: Yellow/Green | Triangle Shapes | Highest Pitch Brass | Staccato 
- BITTER: Purple/Black | Star Shapes | Low Bass / Distortion | Robust
- SPICY: Red/Orange | Pointy/Jagged | Fast Tempo / Bit-crushed | Aggressive