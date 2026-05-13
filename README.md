# DDOT-bus-school-schedules
Checking alignment between school schedules and Detroit city bus schedules. When buses arrive at school either too close or too far from the bell, students must decide between waiting long stretches and being late to class.
The analysis included 23 Detroit Public School Community District (DPSCD) high schools. To simplify the analysis, charter schools were excluded, along with schools that may offer transportation or that operate on irregular schedules, such as career and technical education schools and the Jerry L. White Center.
We used publicly available location data for schools and city bus stops to calculate the four stops closest to each school. Schools are frequently served by more than one bus route, and each route has one stop for each direction of travel. Most schools had at least four stops within a quarter mile.
We collected bus schedule data through a DDOT API. We gathered bell schedules for each school from their district website pages.
We considered bus and school schedules to be misaligned if students had to wait at least 30 minutes before or after school: a conservative measure of inconvenience by public transit standards. 
We excluded buses that arrived fewer than six minutes (the typical walk time from stops to schools in our analysis) before the first bell or after the last bell, since in most cases this would not leave enough time for the walk between the bus stop and class, assuming students walk at 2.5 miles per hour.
At eight of the 23 schools we analyzed, buses were scheduled to arrive 30 minutes or more before the first bell — or just a few minutes before the bell, with a long gap since the earlier bus. At seven other schools, students would have to wait at least 30 minutes after the last bell for the first available bus.
The analysis does not account for the fact that DDOT buses are frequently late, which makes getting to school by bus even more of a challenge.
Data sources:
DDOT API, e.g. https://ddot.info/page-data/stop/6361/page-data.json
Stop coordinates source: https://data.detroitmi.gov/datasets/ddot-bus-stops/about 
School coordinates source: https://data.detroitmi.gov/datasets/e4c70616f7dd4468b3ae128505a46ed0_0/explore?filters=eyJHUkFERV9MRVZFTFMiOlsiOSwxMCwxMSwxMiJdfQ%3D%3D&location=42.356860%2C-83.096697%2C10.
Bell schedules: Assembled by hand as of May 13, 2026 using school sites on detroitk12.org. Data is included in Originals folder
