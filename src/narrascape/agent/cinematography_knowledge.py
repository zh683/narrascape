"""Cinematography knowledge base — the visual grammar that LLM directors reference.

This is NOT a rules engine. It is a reference library of cinematic concepts
that the PromptDirector passes to the LLM as context, allowing the LLM to make
informed creative decisions rather than template-filling.

Key principle: The LLM is the director. This file is the director's library.
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════
# Shot Type Knowledge
# ═══════════════════════════════════════════════════════════════════

SHOT_TYPE_KNOWLEDGE = """
## Shot Types (景别) — Choose intentionally based on narrative purpose

- EXTREME_WIDE_SHOT / ESTABLISHING: Show the world. Use for scale, isolation, geography. Makes subject feel small. Works for landscapes, cityscapes, vast spaces.
- WIDE_SHOT: Subject in full, with environment. Shows relationship between character and space. Good for action, movement, environment as character.
- MEDIUM_SHOT: Waist-up. Standard dialogue framing. Balances subject and context. Most versatile.
- MEDIUM_CLOSE_UP: Chest-up. Slightly more intimate than medium. Shows expression without losing context.
- CLOSE_UP: Face fills frame. Intimacy, emotion, reaction. The viewer is IN the moment. Shallow depth of field.
- EXTREME_CLOSE_UP: Eyes, lips, hands, texture. Abstract, visceral. Forces attention to detail. Creates tension.
- OVER_SHOULDER: Looking past one subject at another. Dialogue, power dynamics, spatial relationships.
- TWO_SHOT: Two subjects in frame. Relationship dynamics, comparison, contrast.
- INSERT / DETAIL: Object, prop, text, texture. Storytelling through things. Creates meaning through symbolism.
- SILHOUETTE: Backlit outline. Mystery, anonymity, dramatic contrast. Pure shape and gesture.
- POINT_OF_VIEW (POV): What the character sees. Immersion, subjective experience.
- AERIAL / DRONE: Bird's eye. God-like perspective, overview, patterns in landscape. Can feel detached or omniscient.
- LOW_ANGLE: Camera below subject. Power, dominance, monumentality. Makes subject look heroic or threatening.
- HIGH_ANGLE: Camera above subject. Vulnerability, weakness, overview. Looking down on the world.
- DUTCH_ANGLE: Tilted horizon. Disorientation, unease, psychological tension. Use sparingly.
"""


# ═══════════════════════════════════════════════════════════════════
# Camera & Lens Knowledge
# ═══════════════════════════════════════════════════════════════════

CAMERA_LENS_KNOWLEDGE = """
## Camera & Lens Language

### Focal Length (焦距) — The psychology of perspective
- 14-24mm (Ultra-wide): Distortion, immersion, environmental scale. Can feel overwhelming or intimate depending on proximity.
- 24-35mm (Wide): Natural human field of view. Documentary feel, environmental context. 35mm is the classic "invisible" lens.
- 50mm (Normal): Neutral, human perspective. Honest, unforced. Great for portraits with natural proportions.
- 85mm (Portrait): Flattering compression, shallow depth of field. Separates subject from background. Intimate but not invasive.
- 100-135mm (Telephoto): Compression, isolation, surveillance feel. Flattened perspective. Emotional distance.
- 200mm+ (Super-telephoto): Extreme compression, voyeuristic. Subject unaware of camera. Sports, wildlife, paparazzi feel.

### Aperture (光圈) — Depth and focus as storytelling
- f/1.4 - f/2.8 (Wide open): Extreme shallow depth of field. Bokeh, subject isolation, dreamlike. Intimate moments, secrets.
- f/4 - f/5.6 (Moderate): Some background context, controlled blur. Balanced. Good for environmental portraits.
- f/8 - f/11 (Stopped down): Deep focus. Everything sharp. Landscape, architecture, detail. Clarity, truth, observation.
- f/16+ (Diffraction): Extreme depth but soft detail. Artistic softness, vintage feel.

### Depth of Field Strategies
- Shallow DOF: Emotional, subjective, isolating. Guides eye to what matters.
- Deep DOF: Objective, observational, democratic. Everything matters.
- Rack focus (shifting focus): Narrative shift, revelation, attention redirection.
- Split focus (both near and far): Complex relationships, irony, layered meaning.

### Camera Movement — The grammar of motion
- STATIC: Observation, contemplation, formal. Time passes within the frame.
- SLOW PUSH-IN: Growing intimacy, revelation, approaching truth. 1-2% per frame.
- SLOW PULL-OUT: Widening perspective, revealing context, withdrawal. Loss of intimacy.
- PAN (horizontal): Following motion, landscape traversal, scanning. Direction implies narrative (left=back, right=forward in Western cinema).
- TILT (vertical): Ascent, descent, looking up/down, awe or vulnerability.
- TRACK/DOLLY (physical movement): Presence in space, following subject, journey.
- CRANE/JIB (arc): Elevation, transcendence, sweeping overview. God-like perspective.
- HANDHELD: Immediacy, documentary, chaos, realism. Unstable emotions.
- STEADICAM: Fluid movement, dreamlike, continuous journey through space.
- ZOOM: Mechanical, artificial, surveillance. Can feel aggressive or detached.
"""


# ═══════════════════════════════════════════════════════════════════
# Lighting Knowledge
# ═══════════════════════════════════════════════════════════════════

LIGHTING_KNOWLEDGE = """
## Lighting Design — The soul of the image

### Light Quality (光的质感)
- HARD LIGHT: Sharp shadows, crisp edges. Drama, tension, midday sun, noir. Creates defined form through shadow.
- SOFT LIGHT: Diffused, gentle shadows. Romance, beauty, overcast, window light. Flattering, forgiving.
- VOLUMETRIC LIGHT: Beams through atmosphere. Dust, fog, haze, god rays. Spiritual, mysterious, cinematic.
- BOUNCE LIGHT: Reflected, indirect. Natural feel, ambient realism, fill.
- PRACTICAL LIGHT: In-world sources (lamp, candle, screen). Motivated, believable, diegetic.

### Key Lighting Setups (经典布光方案)
- THREE-POINT LIGHTING: Key + Fill + Back. Classic portrait. Professional, balanced. Key defines form, fill softens shadows, back separates from background.
- REMBRANDT LIGHTING: Key at 45°, slight fill. Triangle of light on cheek. Classic, painterly, dignified. Portraits, interviews, drama.
- BUTTERFLY / PARAMOUNT: Key above center, creates shadow under nose. Glamour, Hollywood, beauty. Symmetrical, flattering.
- SPLIT LIGHTING: Key at 90°. Half face lit, half shadow. Dramatic, mysterious, noir, psychological tension.
- LOOP LIGHTING: Key slightly above and to side. Small shadow loop under nose. Natural, flattering, versatile.
- CHIAROSCURO: Extreme contrast. Deep shadows, bright highlights. Baroque, dramatic, Caravaggio. Tension, mystery, moral ambiguity.
- LOW-KEY: Predominantly dark. Minimal light sources. Noir, horror, suspense, intimacy. What you DON'T see matters.
- HIGH-KEY: Predominantly bright. Even, flat lighting. Comedy, innocence, commercials, utopia. Optimistic, safe.
- SILHOUETTE / RIM LIGHT: Backlight only. Pure form, anonymity, drama. Separation from background. Mystical, threatening, elegant.
- CANDLELIGHT / FIRELIGHT: Warm, flickering, intimate. Historical, romantic, primal. Creates organic movement in light.
- BLUE HOUR / MAGIC HOUR: Dawn/dusk. Soft, warm/cool gradient. Romantic, transitional, fleeting beauty.
- NEON / ARTIFICIAL: Urban, nightlife, cyberpunk. Color contrast, moody, artificial beauty. Contemplation, isolation.
- OVERCAST / FLAT: Diffused, no shadows. Melancholic, muted, documentary, truth. Emotional flatness.
- MOTOR VEHICLE LIGHTING: Headlights, taillights, dashboard glow. Journey, night driving, isolation in motion.

### Color Temperature (色温)
- WARM (2000K-4000K): Candlelight, sunrise, sunset, tungsten. Intimacy, nostalgia, safety, sunset.
- NEUTRAL (5000K-6500K): Daylight, overcast. Neutral, documentary, objective.
- COOL (7000K-10000K): Shade, dusk, fluorescent, moonlight. Isolation, melancholy, night, mystery, technology.
- COLOR CONTRAST: Warm vs cool in same frame. Tension, drama, visual interest. Teal-and-orange is classic cinematic grade.

### Special Light Phenomena (特效光效)
- LENS FLARE: Light hitting lens. Cinematic, anamorphic, romantic, disruption. Breaks fourth wall slightly.
- HALATION: Glow around bright areas. Film-like, dreamy, vintage. Softens harsh highlights.
- BLOOM: Light bleeding beyond edges. Dreamlike, ethereal, overexposed beauty.
- CAUSTICS: Light patterns through water/glass. Refraction, detail, movement.
- GOD RAYS / Crepuscular: Light through atmosphere. Spiritual, awe, cathedral-like.
- SHADOW PLAY: Patterns on surfaces. Texture, time of day, visual interest. Venetian blinds, tree shadows, lattice.
"""


# ═══════════════════════════════════════════════════════════════════
# Composition Knowledge
# ═══════════════════════════════════════════════════════════════════

COMPOSITION_KNOWLEDGE = """
## Composition — The architecture of the frame

### Framing Principles
- RULE OF THIRDS: Divide frame into 3x3 grid. Place subject at intersections. Natural, balanced, dynamic. Most versatile.
- CENTER FRAMING: Symmetrical, formal, confrontational. Wes Anderson style, Kubrick. Direct address to viewer.
- LEADING LINES: Roads, rivers, architectural lines guide eye. Depth, movement, direction. Strong visual flow.
- SYMMETRY: Reflections, architecture, balanced frames. Order, perfection, artificial beauty, unease (when broken).
- ASYMMETRY: Dynamic tension, imbalance, energy. Realistic, spontaneous, documentary feel.
- NEGATIVE SPACE: Empty areas around subject. Isolation, loneliness, contemplation, minimalism. Breathing room.
- FRAME WITHIN FRAME: Doorways, windows, mirrors, arches. Layers of reality, voyeurism, confinement, looking.
- FOREGROUND INTEREST: Objects in front of subject. Depth, layering, immersion. Branches, rocks, people walking past.
- DEPTH LAYERS: Foreground, midground, background all active. Complex, rich, observational. Renaissance painting influence.
- OVERHEAD / BIRD'S EYE: Patterns, geometry, abstraction. Maps, overview, strategic perspective.
- WORM'S EYE: Looking straight up. Architecture, sky, monumentality. Overwhelming, vertigo.

### Aspect Ratio Psychology
- 2.39:1 (CinemaScope): Epic, widescreen, landscape, horizontal sweep. Cinematic, grand, expensive feel.
- 16:9 (Standard): Balanced, modern, versatile. TV, documentary, general purpose.
- 4:3 (Academy): Classic, nostalgic, intimate, square-ish. Old Hollywood, TV shows, 90s nostalgia.
- 1:1 (Square): Social media, confined, focused, modern. Instagram, TikTok.
- 9:16 (Vertical): Mobile, portrait, intimate, social. Stories, vertical video, phone-native.
- 2:1 (18:9): Modern digital cinema. Slightly wider than 16:9, premium feel. Netflix original.

### Spatial Relationships
- FOREGROUND: Elements close to camera. Creates depth, immersion, framing. Often out of focus in shallow DOF.
- MIDGROUND: Primary subject area. Where the action happens. Balanced attention.
- BACKGROUND: Context, environment, atmosphere. Can be sharp (deep DOF) or blurred (shallow DOF).
- ATMOSPHERIC PERSPECTIVE: Distant objects hazier, less saturated. Depth, distance, scale. Natural realism.
"""


# ═══════════════════════════════════════════════════════════════════
# Color Grading & Atmosphere
# ═══════════════════════════════════════════════════════════════════

COLOR_ATMOSPHERE_KNOWLEDGE = """
## Color Grading & Atmosphere (色调与氛围)

### Color Palette Strategies
- MONOCHROMATIC: Single hue family. Elegant, unified, minimalist. Can be warm or cool. Strong mood.
- COMPLEMENTARY: Opposite colors (blue-orange, green-red). Tension, drama, vibrancy. Classic cinematic grade.
- ANALOGOUS: Adjacent colors (blue-teal-green). Harmony, calm, natural. Underwater, forest, twilight.
- TRIADIC: Three evenly spaced colors. Vibrant, balanced, playful. Less common in serious cinema.
- WARM DOMINANT: Gold, amber, orange. Nostalgia, warmth, romance, sunset, golden hour.
- COOL DOMINANT: Blue, teal, cyan. Isolation, technology, night, melancholy, clinical.
- DESATURATED / MUTED: Low saturation. Gritty, realistic, documentary, post-apocalyptic, serious.
- HIGH SATURATION: Vibrant, stylized, comic-book, fantasy, advertising, pop art.
- SEPIA / DUOTONE: Vintage, historical, memory, faded photograph. Nostalgic, timeless.
- BLEACH BYPASS: Silver retention. High contrast, desaturated, gritty. War films, 2000s cinema. Cold, metallic.
- TEAL-AND-ORANGE: Shadows teal, highlights orange. Blockbuster grade, popular, pleasing to eye. Warm/cool contrast.
- DAY-FOR-NIGHT: Blue-tinted, underexposed. Moonlight illusion, fantasy, stylized. Classic technique.
- CROSS-PROCESSING: Chemical film manipulation. Unpredictable colors, high contrast. Experimental, music video.
- INFRARED: False color. White foliage, dark sky. Surreal, alien, scientific. Experimental.

### Atmosphere & Texture
- FOG / MIST: Soft, mysterious, depth layers. Horror, romance, morning, liminal space.
- RAIN / WET: Reflections, moody, melancholy. Urban, noir, romantic. Surfaces catch light.
- SNOW: Blank, isolating, quiet. Exposure challenges, blue shadows, overexposed highlights. Serene or hostile.
- DUST / PARTICLES: Volume, light beams, age, decay. Historical, abandoned, spiritual. Time passing.
- SMOKE / HAZE: Atmospheric, volumetric, diffusion. Concert, battle, dreamlike, industrial.
- STEAM: Volumetric, organic, warm. Coffee, cooking, baths, industrial. Intimate moments.
- SPLASH / WATER: Dynamic, movement, energy. Ocean, rain, fountains. Refreshing, powerful, chaotic.
- LEAVES / PETALS: Gentle, falling, seasonal. Beauty, transience, poetic. Spring, autumn, death.
- SPARKS / EMBERS: Danger, warmth, destruction. Campfire, forge, explosion. Intense, primal.
- FIRE / FLAMES: Warm, dangerous, primal. Campfire, candles, destruction. Flickering light, shadows dance.
- BROKEN GLASS / REFLECTIONS: Fragmented reality, urban decay, beauty in destruction. Complex light.
- RUST / DECAY: Texture, time, history, post-apocalyptic. Beauty in imperfection, wabi-sabi.
- METAL / INDUSTRIAL: Cold, modern, sharp. Reflections, precision, alienation. Future, technology.
- WOOD / NATURAL: Warm, organic, history. Grain, texture, age. Earth, tradition, craftsmanship.
- FABRIC / TEXTILE: Softness, movement, luxury. Silk, velvet, linen. Fashion, elegance, comfort.
- SKIN / FLESH: Intimacy, humanity, vulnerability. Pores, texture, wrinkles, scars. Life, aging.
"""


# ═══════════════════════════════════════════════════════════════════
# Negative Prompt Knowledge (Common AI Flaws to Avoid)
# ═══════════════════════════════════════════════════════════════════

NEGATIVE_PROMPT_KNOWLEDGE = """
## Negative Prompt Design — What to exclude for quality

### Common AI Artifacts (通用缺陷)
- Blurry, out of focus, low resolution, pixelated
- Deformed hands, extra fingers, fused fingers, missing fingers
- Bad anatomy, disfigured, malformed, mutated, extra limbs
- Watermark, signature, text, logo, cropping frame, UI elements
- Oversaturated, overexposed, underexposed, blown highlights
- Noise, grain (unless intentional), compression artifacts
- Duplicate, cloned, mirrored subjects
- Jagged edges, aliasing, moiré patterns
- Plastic skin, smooth skin, airbrushed, overly perfect skin
- Anime, cartoon, illustration, painting (when aiming for photorealism)

### Photorealism Killers (写实破坏者)
- Uncanny valley: eyes too large, skin too smooth, proportions slightly off
- Floating objects, objects not grounded, gravity-defying
- Inconsistent scale, wrong perspective, impossible geometry
- Muddy textures, waxy surfaces, plastic look
- Perfect symmetry (except when intentional)
- Flat lighting with no shadow direction
- Uniform color without variation or texture
- Cartoonish proportions, exaggerated features
- Clean, pristine environments (unless intentional)
- Perfectly straight lines in nature

### Cinematic Quality Killers (电影感破坏者)
- Flat, even lighting (no shadow direction, no depth)
- Centered, dead-center composition (unless formal/symmetrical intent)
- Bright, saturated colors everywhere (no tonal range)
- Sharp focus on everything (no depth of field)
- Eye-level, straight-on angle (no dynamism)
- No atmospheric perspective (distant objects as sharp as foreground)
- No texture detail (smooth, plastic surfaces)
- Incorrect lens distortion (fisheye when not intended)
- Unnatural skin tones (too orange, too pink, too gray)
- Cluttered composition with no clear subject
- Harsh flash photography look
- Amateur snapshot aesthetic
"""


# ═══════════════════════════════════════════════════════════════════
# Video-First Considerations
# ═══════════════════════════════════════════════════════════════════

VIDEO_FIRST_KNOWLEDGE = """
## Video-First Image Design (视频首帧设计原则)

When designing images that will become keyframes for video generation (Sora, Runway, Kling, Veo, etc.), additional considerations apply:

### Spatial Consistency for Motion (运动空间一致性)
- Ensure subject has room to move within frame. If camera will push in, subject shouldn't be too large already.
- If panning, the composition should have visual interest extending beyond frame edges.
- If tilting up, the upper frame should have something worth revealing (sky, architecture, monument).
- If tracking, the subject should be positioned to allow natural movement direction.
- Leave "headroom" for upward motion, "lead room" for forward motion (subject looks into empty space).

### Temporal Continuity (时间连续性)
- Adjacent keyframes should share: color temperature, lighting direction, atmospheric conditions, overall mood.
- If transitioning from interior to exterior, consider how light changes (warm interior light vs cool exterior).
- If time passes between shots, lighting should reflect that (morning → noon → evening → night).
- Weather consistency: if it's raining in shot 1, it shouldn't be sunny in shot 2 unless intentional.
- Shadow direction should be consistent unless the sun has moved (which implies time passage).

### Motion-Ready Composition (运动就绪构图)
- Avoid edge-locked subjects that will be cut off by camera movement.
- Consider parallax: foreground, midground, background layers move at different speeds during motion.
- If doing a slow push-in, the subject should have enough detail to survive magnification.
- If doing a zoom out, the frame edges should be visually acceptable (no awkward cropping).
- For Ken Burns zoom, the image needs 20%+ resolution headroom beyond the target output resolution.

### Image Quality for Video Input (视频输入图像质量要求)
- Minimum 1280×768 for most video models (Runway, Pika, Kling).
- Higher is better: 1920×1080 or 2560×1440 for premium models (Sora, Veo).
- 16:9 aspect ratio is standard for video. 2.39:1 for cinematic widescreen. 9:16 for vertical.
- Sharp focus on primary subject. Slight softness on edges is acceptable (and cinematic).
- Consistent lighting across the entire frame. Sudden lighting changes confuse video models.
- High dynamic range. Preserved highlights and shadows. Avoid blown-out whites or crushed blacks.
- Clean, professional composition. Avoid snapshot aesthetics.
- Smooth gradients in sky, water, skin. Banding artifacts from 8-bit compression are visible in video.
- Color space: sRGB is safe. Wide gamut (P3, Rec.2020) if the target platform supports it.
"""


# ═══════════════════════════════════════════════════════════════════
# Assemble Full Knowledge
# ═══════════════════════════════════════════════════════════════════

FULL_CINEMATOGRAPHY_KNOWLEDGE = (
    SHOT_TYPE_KNOWLEDGE
    + "\n"
    + CAMERA_LENS_KNOWLEDGE
    + "\n"
    + LIGHTING_KNOWLEDGE
    + "\n"
    + COMPOSITION_KNOWLEDGE
    + "\n"
    + COLOR_ATMOSPHERE_KNOWLEDGE
    + "\n"
    + NEGATIVE_PROMPT_KNOWLEDGE
    + "\n"
    + VIDEO_FIRST_KNOWLEDGE
)
