"""Sample catalogue: the SEED DATA for the database.

IMPORTANT: every category, service, price and provider below is SAMPLE DATA
for development. None of it represents a real business or a real price.

This module is only used by the seeding command (flask seed-db) and by tests.
The website itself reads services from the database, not from this file.
It has no database imports, so it can be checked without any extra packages.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SampleCategory:
    slug: str
    name: str
    icon: str
    blurb: str


@dataclass(frozen=True)
class SampleService:
    slug: str
    name: str
    category_slug: str
    summary: str
    description: str
    price_from: int  # sample starting price in Indian rupees
    duration: str
    includes: tuple
    provider_name: str
    provider_area: str
    provider_bio: str


CATEGORIES = (
    SampleCategory("plumbing", "Plumbing", "droplet", "Leaks, taps, pipes and bathroom fittings."),
    SampleCategory("electrical", "Electrical Repairs", "zap", "Switches, sockets, wiring, fans and lights."),
    SampleCategory("ac-repair", "AC Repair & Maintenance", "wind", "Air conditioner servicing, repair and installation."),
    SampleCategory("laptop-repair", "Laptop & Computer Repair", "laptop", "Hardware fixes, software problems and data backup."),
    SampleCategory("bike-repair", "Motorcycle & Bike Repair", "bike", "Routine servicing, brakes, chains and tune-ups."),
    SampleCategory("home-cleaning", "Home Cleaning", "sparkles", "Deep cleaning for homes, kitchens and bathrooms."),
)

SERVICES = (
    SampleService(
        "leak-detection-pipe-repair", "Leak Detection & Pipe Repair", "plumbing",
        "Find and fix dripping taps, damp walls and leaking pipes.",
        "A plumber inspects the problem area, finds the source of the leak and repairs or replaces the damaged section of pipe or fitting. Describe where you see water or damp patches when you book.",
        399, "1 to 2 hours",
        ("Inspection of the affected area", "Repair of minor pipe and tap leaks", "Basic fittings and sealant", "Clean-up after the job"),
        "Sample Provider A (Plumbing)", "Central zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "bathroom-fixture-installation", "Bathroom Fixture Installation", "plumbing",
        "Install or replace taps, showers, wash basins and flush tanks.",
        "Get new bathroom fixtures fitted neatly and tested for leaks. Bring the fixtures you bought, or ask the provider what they recommend.",
        499, "1 to 3 hours",
        ("Removal of the old fixture", "Fitting of the new fixture", "Leak and pressure test", "Waste removal"),
        "Sample Provider B (Plumbing)", "North zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "switch-socket-wiring-repair", "Switch, Socket & Wiring Repair", "electrical",
        "Fix loose switches, burnt sockets and tripping circuits.",
        "An electrician checks the faulty switch, socket or circuit, repairs or replaces it and tests that it works safely. Tell us what happens, for example sparks, a burning smell or a breaker that trips.",
        349, "1 to 2 hours",
        ("Safety check of the circuit", "Replacement of faulty switches or sockets", "Testing after the repair", "Advice on any bigger wiring issues"),
        "Sample Provider C (Electrical)", "Central zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "fan-light-fitting", "Ceiling Fan & Light Fitting", "electrical",
        "Install or replace ceiling fans, tube lights and decorative lights.",
        "Have a new fan or light fitting mounted securely and wired correctly. Useful for new rooms, replacements and upgrades to LED fittings.",
        299, "1 hour",
        ("Mounting and wiring of the fitting", "Regulator or switch connection", "Function test"),
        "Sample Provider D (Electrical)", "East zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "ac-servicing-gas-check", "AC Servicing & Gas Check", "ac-repair",
        "Clean filters and coils, check cooling and gas pressure.",
        "A technician cleans your air conditioner, checks the cooling performance and gas pressure, and tells you if a repair is needed. Good to schedule before summer.",
        599, "1 to 1.5 hours",
        ("Filter and coil cleaning", "Cooling performance check", "Gas pressure check", "Drain line check"),
        "Sample Provider E (AC)", "South zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "split-ac-installation", "Split AC Installation", "ac-repair",
        "Mount and connect a new split air conditioner.",
        "Installation of the indoor and outdoor units, pipe connection, drain setup and a trial run. Brackets and extra piping may be charged separately.",
        1199, "2 to 3 hours",
        ("Indoor and outdoor unit mounting", "Pipe and drain connection", "Trial run and cooling check"),
        "Sample Provider F (AC)", "Central zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "laptop-screen-battery-replacement", "Laptop Screen & Battery Replacement", "laptop-repair",
        "Replace a cracked screen, weak battery or faulty keyboard.",
        "A technician diagnoses the hardware fault and replaces the part. Share your laptop brand and model in the problem description so the right part can be arranged.",
        899, "1 to 3 hours",
        ("Hardware diagnosis", "Part replacement", "Testing after repair"),
        "Sample Provider G (Computers)", "North zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "virus-removal-os-reinstall", "Virus Removal & OS Reinstall", "laptop-repair",
        "Fix a slow computer, remove malware and reinstall Windows.",
        "Clean up a slow or infected computer, reinstall the operating system if needed and set up the essential software. Ask for a data backup first if you have files you need to keep.",
        499, "1 to 3 hours",
        ("Malware scan and removal", "Operating system reinstall if needed", "Driver and basic software setup", "Optional data backup"),
        "Sample Provider H (Computers)", "East zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "motorcycle-general-service", "Motorcycle General Service", "bike-repair",
        "Oil change, air filter, spark plug and a full safety check.",
        "A routine service keeps your motorcycle reliable. The mechanic changes the oil, cleans the filter, checks the plug, lights, tyres and brakes, and reports anything that needs attention.",
        449, "1 to 2 hours",
        ("Engine oil change", "Air filter and spark plug check", "Brake, tyre and light inspection", "Chain cleaning and lubrication"),
        "Sample Provider I (Bikes)", "West zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "brake-chain-maintenance", "Brake & Chain Maintenance", "bike-repair",
        "Replace brake pads, adjust the chain and fix a spongy brake.",
        "If your bike brakes feel weak or the chain is noisy or loose, a mechanic can adjust or replace the worn parts and test ride the result.",
        349, "1 hour",
        ("Brake pad check or replacement", "Chain adjustment and lubrication", "Test ride"),
        "Sample Provider J (Bikes)", "South zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "full-home-deep-cleaning", "Full Home Deep Cleaning", "home-cleaning",
        "Top-to-bottom cleaning of rooms, floors, kitchen and bathrooms.",
        "A cleaning team deep cleans your home, including floors, windows you can reach, fans, kitchen surfaces and bathrooms. Tell us the size of your home when you book.",
        1499, "4 to 6 hours",
        ("Dusting and floor scrubbing", "Kitchen surface and sink cleaning", "Bathroom scrubbing", "Fan and switchboard wipe-down"),
        "Sample Provider K (Cleaning)", "Central zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
    SampleService(
        "kitchen-bathroom-cleaning", "Kitchen & Bathroom Cleaning", "home-cleaning",
        "Focused cleaning for the two hardest-working rooms in your home.",
        "Remove grease, limescale and stains from kitchen counters, chimney filters, sinks, tiles and bathroom fittings.",
        699, "2 to 3 hours",
        ("Degreasing of kitchen surfaces", "Tile and fitting scrubbing", "Sink and drain cleaning"),
        "Sample Provider L (Cleaning)", "East zone (sample)",
        "Sample profile for development. A real provider profile will show experience, service areas and reviews.",
    ),
)
