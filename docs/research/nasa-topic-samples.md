# NASA scientific samples for the Polaris catalogs

Verified on 12 October 2026. These are measured science products, converted locally
from public archive responses into Zarr arrays in Icechunk. The import retains the
downloaded responses, source URLs, selection, hashes, native parameter attributes and
conversion description.

## International Space Station: TSIS-1 TIM

NASA identifies TSIS-1 as an ISS instrument package. Its Total Irradiance Monitor
measures the Sun's total irradiance; LASP builds and operates the instrument and
distributes its science data. [NASA mission](https://science.nasa.gov/mission/tsis-1/)

The selected product is the daily Level 3 TIM record, version 05. LASP's release
notes date version 05 to 10 October 2025. The current NASA GES DISC citation uses
DOI **10.5067/TSIS/TIM/DATA310**. The earlier product guide's version-specific DOI
must not replace that current citation. [LASP product](https://lasp.colorado.edu/tsis/data/tsi-data/),
[release notes](https://lasp.colorado.edu/tsis/data/tsi-data/tim-tsi-release-notes/),
[NASA product citation](https://disc.gsfc.nasa.gov/datasets/TSIS_TSI_L3_24HR_05/summary)

| Property | Verified value |
| --- | --- |
| Local catalog | `international_space_station` |
| Namespace | `instruments / tsis_1` |
| Table | `total_solar_irradiance` |
| Selection | 2020-01-01 inclusive through 2021-01-01 exclusive |
| Download | 366 rows, 14 native columns, 39,024 bytes |
| CSV SHA-256 | `04b89dfc4594a184eb0dd69322e255d87ab0b8e4455c4e542664577728abbfdd` |
| Original local CSV | `.local/polaris/source-files/tsis_tsi_24hr_2020.csv` |

The [bounded CSV request](https://lasp.colorado.edu/lisird/latis/dap/tsis_tsi_24hr.csv?time%3E=2020-01-01&time%3C2021-01-01)
was downloaded without credentials. Preserve both `tsi_1au` and `tsi_true_earth` in
W/m², all instrument accuracy/precision and solar deviation/measurement uncertainty
columns, Julian Dates, measurement-date deviation, and `provisional_flag`. LASP
describes the two irradiance series as measurements normalized to one astronomical
unit and at the actual Earth-to-Sun distance. [Product description](https://lasp.colorado.edu/tsis/data/tsi-data/)

Native LaTiS attributes are available as
[JSOND metadata](https://lasp.colorado.edu/lisird/latis/dap/tsis_tsi_24hr.jsond?limit(0))
and [DAP attributes](https://lasp.colorado.edu/lisird/latis/dap/tsis_tsi_24hr.das).
They explicitly declare `missing_value = 0` on the twelve measurement/date-deviation
fields, excluding nominal `time` and `provisional_flag`. The downloaded 2020 CSV
contains forty zero-valued irradiance records. Retain their numeric values and encode
the source's missing-value attributes; do not interpolate or treat them as measured
zero solar flux. The HAPI metadata reports null fill values and therefore cannot be
the authority for this source's missing-value convention.

The [TIM data guide, Table 6](https://docserver.gesdisc.eosdis.nasa.gov/public/project/TSIS/159520RevA_TSIS_Data_User_Guide.pdf)
defines `provisional_flag` as final (`0`) or provisional (`1`), rather than a general
validity flag. Retain its zeros as valid status values. The source's daily timestamps
refer to the nominal observation interval; original Julian Dates remain in `time`.
A separate `time_unix_ns` explicitly records the conversion to UTC nanoseconds.
For the first sample, Julian Date `2458850.0` converts to
`2020-01-01T12:00:00Z`, independently confirmed against the
[archive's UTC delivery](https://lasp.colorado.edu/lisird/latis/hapi/data?id=tsis_tsi_24hr&time.min=2020-01-01T00:00:00Z&time.max=2020-01-02T00:00:00Z&format=csv).

NASA's [collection metadata](https://cmr.earthdata.nasa.gov/search/collections.umm_json?short_name=TSIS_TSI_L3_24HR&version=05)
points to EOSDIS data-use guidance and GES DISC citation guidance. It does not specify
an SPDX license. Record those links and the current citation without inventing a
Creative Commons identifier. [NASA data-use guidance](https://earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance),
[GES DISC citation guidance](https://disc.gsfc.nasa.gov/data-guidelines)

## Heliophysics: ACE MAG

The ACE MAG Level 2 product provides nominal 16-second averages of magnetic-field
magnitude and Cartesian vectors in GSE and GSM coordinates. Its NASA SPASE record
identifies DOI **10.48322/e0dc-0h53**, open access and **CC0-1.0**, and requests
acknowledgment of the instrument team, ACE Science Center and NASA GSFC/SPDF CDAWeb.
[NASA SPASE product record](https://spase-metadata.org/NASA/NumericalData/ACE/MAG/L2/PT16S)

The selected [CDAWeb HAPI CSV](https://cdaweb.gsfc.nasa.gov/hapi/data?id=AC_H0_MFI&parameters=Time,Magnitude,BGSEc,BGSM,dBrms&time.min=2020-01-01T00:00:00Z&time.max=2020-01-02T00:00:00Z&format=csv)
contains 5,401 observations for 2020-01-01, with `Time`, `Magnitude`, `BGSEc`, `BGSM`
and `dBrms`. Magnetic values use nT. Preserve the actual timestamps and vector
components; a nominal cadence does not authorize constructing a regular time grid.
The published missing-data sentinel is `-1e31`, which remains in raw arrays with
matching missing-value metadata. [HAPI parameter metadata](https://cdaweb.gsfc.nasa.gov/hapi/info?id=AC_H0_MFI),
[NASA CDAWeb instrument notes](https://cdaweb.gsfc.nasa.gov/misc/NotesA.html#AC_H0_MFI)

## Alternatives checked

SAGE III/ISS provides atmospheric profiles and GEDI provides forest structure and
biomass data from ISS instruments. Their current NASA distribution paths require
Earthdata authentication. TSIS-1 supplies a scientific sample through the instrument
team's public archive without credentials, making it suitable for this
local setup. [SAGE III mission/data access](https://science.nasa.gov/mission/sage/sage-iii-iss/),
[Earthdata access documentation](https://urs.earthdata.nasa.gov/documentation/what_do_i_need_to_know),
[NASA GEDI registry access requirements](https://registry.opendata.aws/nasa-gedi/)
