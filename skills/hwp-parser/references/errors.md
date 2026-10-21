# Error and warning codes

On failure `hwp2md.py` exits 2 and the last stderr line is
`{"status":"failed","error":CODE,"message":...}`. No output file or assets folder is left
behind. Warnings never fail a run; they are listed in the `warnings` array of the success
summary. Codes ending in `:<id>` name an asset (`a0`, `a1`, …) or a package part.

Retrying the same command without changing something will fail the same way: none of
these failures is transient except the network ones under `--vlm`.

## Input and format

| Code | Meaning | Remedy |
| --- | --- | --- |
| `USAGE_ERROR` | Invalid command-line arguments. | Check the flags: `INPUT [--out-dir DIR] [--force] [--ocr] [--pdf FILE\|auto] [--vlm groq\|xai]`, or `--check-vlm groq\|xai` alone (it takes no INPUT or other flags). Quote paths with spaces. |
| `MISSING_OR_OVERSIZE_INPUT` | Input missing, not a regular file, or over 128 MiB. | Check the path (absolute, quoted). Split or re-save very large documents. |
| `UNSUPPORTED_SIGNATURE_HWP3_OR_OTHER` | Neither HWP 5 nor HWPX (e.g. HWP 3, PDF, a renamed text or image file). | Confirm the real format. Re-save HWP 3 files as HWP/HWPX in Hancom Office; use another tool for other formats. |
| `NOT_HWP5` | An OLE file without an HWP `FileHeader` stream. | Probably another Office format with an `.hwp` name; confirm the format. |
| `UNSUPPORTED_HWP_VERSION` | The OLE file header is not a supported HWP 5 header. | Re-save the document in current Hancom Office (HWP or HWPX). |
| `NOT_HWPX_MIMETYPE` | A ZIP without the HWPX mimetype. | Not an HWPX package (maybe DOCX/ODT/ZIP); confirm the format or re-save as HWPX. |

## Protected documents (no decryption)

| Code | Meaning | Remedy |
| --- | --- | --- |
| `PASSWORD_PROTECTED_HWP` | The HWP is password protected. | Ask the user to remove the password in Hancom Office and save an unprotected copy. |
| `DISTRIBUTION_HWP_REQUIRES_AUTHORIZED_CONVERSION` | A distribution (read-only) HWP. | Convert it with an authorized Hancom viewer, or export a PDF and convert that with another tool. |
| `DRM_OR_CERTIFICATE_ENCRYPTED_HWP` | DRM or certificate encrypted. | Must be decrypted by the user's authorized DRM/certificate software first. |
| `ENCRYPTED_PACKAGE` | The HWPX package is encrypted. | Save an unencrypted copy in Hancom Office. |

## Damaged or unsafe packages

| Code | Meaning | Remedy |
| --- | --- | --- |
| `UNSAFE_PACKAGE_PATH` | A ZIP member path is absolute, contains `..`, `\` or `:`. | Treat the file as suspicious; re-save it from Hancom Office if it is trusted. |
| `XML_DTD_OR_ENTITY_FORBIDDEN` | Document XML declares a DTD or entities. | Rejected for safety; re-save from Hancom Office. |
| `MALFORMED_XML` | Document XML is malformed. | The file is damaged; re-save or re-export it. |
| `INVALID_OR_OVERSIZE_DEFLATE` | A compressed stream is invalid or expands past the limit. | The file is damaged or a decompression bomb; re-save it. |
| `ASSET_TOO_LARGE` | An embedded asset exceeds 64 MiB. | Reduce or remove the very large embedded object and re-save. |
| `ASSETS_TOO_LARGE` | Embedded assets together exceed 256 MiB. | Reduce embedded images/objects, or split the document. |
| `DUPLICATE_OR_TOO_MANY_MEMBERS` | Duplicate ZIP members, or more than 4096. | The package is damaged or unusual; re-save it. |
| `PACKAGE_TOO_LARGE` | The HWPX expands beyond 256 MiB in total, or one member beyond 64 MiB. | Split the document or reduce embedded media. |
| `OLE_TOO_LARGE` | HWP 5 streams exceed the size limit. | Split the document or reduce embedded media. |
| `CONFLICTING_BINDATA_COMPRESSION` | Conflicting compression flags for embedded data. | The file is damaged; re-save it in Hancom Office. |
| `MISSING_PACKAGE_SPINE` | No readable manifest/spine (`Contents/content.hpf`). | Damaged or non-standard HWPX; re-save it. |
| `INVALID_MANIFEST_ID` | Invalid or duplicate manifest item id. | Damaged or non-standard HWPX; re-save it. |
| `BROKEN_SPINE_REFERENCE` | The spine references a missing manifest item. | Damaged HWPX; re-save it. |
| `MISSING_OR_DUPLICATE_SECTIONS` | Body sections missing or duplicated. | Damaged HWPX; re-save it. |
| `SECTION_SPINE_MISMATCH` | Body sections do not match the spine. | Damaged or non-standard HWPX; re-save it. |
| `UNSAFE_ASSET_NAME` | An embedded asset would get an unsafe or duplicate file name. | Should not happen with real documents; report it as a bug with the file type (not the file). |

## HWP 5 reader (pyhwp)

| Code | Meaning | Remedy |
| --- | --- | --- |
| `INSTALL_PYHWP_REQUIREMENTS_IN_THIS_PYTHON` | pyhwp is not importable. | Run through `uv run …/scripts/hwp2md.py` so the pinned environment is used, not plain `python`. |
| `PYHWP_XML_FAILED` | pyhwp failed, timed out (90 s) or hit a resource limit. | The document may be damaged or unusual for pyhwp; re-save it as HWPX in Hancom Office and convert that. |

## Output

| Code | Meaning | Remedy |
| --- | --- | --- |
| `OUTPUT_ALREADY_EXISTS` | `<stem>.md` or `<stem>_assets/` already exists. | Ask before replacing: rerun with `--force`, or choose another `--out-dir`. |
| `NO_EXTRACTABLE_TEXT` | No text in the body (likely scanned images), and OCR found none either. | Retry with `--ocr` (and/or `--pdf FILE`). If it still fails, the images contain no readable text. |

## OCR and `--pdf`

| Code | Meaning | Remedy |
| --- | --- | --- |
| `LITEPARSE_NOT_AVAILABLE` | The LiteParse `lit` command was not found. | Run through `uv run` so the pinned `liteparse` is installed. |
| `TESSDATA_NOT_AVAILABLE` | `tessdata/kor.traineddata` or `eng.traineddata` missing from the skill folder. | Reinstall the skill; the language files ship with it. |
| `LITEPARSE_OCR_FAILED` | LiteParse failed or timed out (180 s) on the `--pdf` file. | Check that the PDF opens; try a smaller or re-exported PDF. (Per-image failures under `--ocr` are warnings instead.) |
| `INVALID_PDF_INPUT` | `--pdf` file missing, over 128 MiB, or not a PDF. | Pass an existing PDF. For a file named `auto`, write it with a directory, e.g. `./auto`. |
| `HWPX_PDF_CONVERSION_UNSUPPORTED` | `--pdf auto` on an HWPX file. | Export a PDF from Hancom Office / Hancom Docs and pass it with `--pdf FILE`. |
| `LOCAL_LIBREOFFICE_NOT_AVAILABLE` | `--pdf auto` found no LibreOffice (`soffice`). | Install LibreOffice, or export a PDF and pass it with `--pdf FILE`. |
| `ODT_CONVERSION_FAILED` | pyhwp could not convert HWP 5 to ODT. | Use an exported PDF with `--pdf FILE` instead. |
| `INVALID_ODT_OUTPUT` | The intermediate ODT is invalid. | Use an exported PDF with `--pdf FILE` instead. |
| `PDF_CONVERSION_FAILED` | LibreOffice failed or timed out converting to PDF. | Use an exported PDF with `--pdf FILE`; check that LibreOffice runs headless. |

## VLM (`--vlm groq|xai`)

| Code | Meaning | Remedy |
| --- | --- | --- |
| `GROQ_API_KEY_MISSING` | `GROQ_API_KEY` is not set (or blank). Nothing was sent. | The user sets `GROQ_API_KEY` in the environment that runs the agent. Never ask for the key in chat. |
| `XAI_API_KEY_MISSING` | `XAI_API_KEY` is not set (or blank). Nothing was sent. | The user sets `XAI_API_KEY` in the environment. Never ask for the key in chat. |
| `GROQ_HTTP_<status>` / `XAI_HTTP_<status>` | The provider answered with an HTTP error (message: `VLM_HTTP_ERROR`). | 401/403: key invalid or lacks access. 404: model unavailable to the account. 413: image too large. 429: rate limit, wait and retry. 5xx: provider outage, retry later. Status `0` means an invalid status. |
| `VLM_HTTP_ERROR` | Generic message shared by all `<PROVIDER>_HTTP_<status>` codes. | See the row above. |
| `VLM_NETWORK_ERROR` | Provider unreachable, TLS failure or 90 s timeout. | Check connectivity / proxy and retry. |
| `VLM_BAD_RESPONSE` | Malformed, non-JSON or oversized (> 4 MiB) response. | Retry once; if it persists, run without `--vlm`. |
| `VLM_UNSUPPORTED_IMAGE` | A prepared image is not PNG/JPEG or exceeds 3 MiB. | Normally such images are skipped (`VLM_SKIPPED`); report it as a bug if seen. |

## Unexpected errors

Any other code (e.g. a Python exception class name such as `OSError`) carries the message
"Unexpected internal error during conversion." Check disk space and permissions on the
output folder; otherwise report it as a bug with the code, the command flags and the file
type (not the document).

## Warnings

| Warning | Meaning | What to do |
| --- | --- | --- |
| `OCR_EMPTY:<id>` | OCR found no text in that image. | Usually a photo or diagram without text; nothing to do. |
| `OCR_FAILED:<id>` | LiteParse failed on that image; the run continued. | Mention that the image was not OCR'd. |
| `OCR_ONLY_TEXT` | All text came from OCR; the document has no direct text. | Tell the user the content is OCR output and may contain errors. |
| `EXPERIMENTAL_PDF_CONVERSION` | `--pdf auto` used LibreOffice rendering. | Treat appended pages with care; prefer a Hancom-exported PDF. |
| `VLM_SKIPPED:<id>` | Image not sent: cannot be decoded (e.g. WMF/EMF, OLE object), over 40 million pixels, or still over 3 MiB after re-encoding. | No VLM note for that image. |
| `VLM_EMPTY:<id>` | The provider returned no text for that image. | No VLM note for that image. |
| `UNINTERPRETED_BINARY:<id>` | Embedded object of unknown type kept as `.bin`. | Often WMF/EMF drawings or OLE objects; content not converted. |
| `UNINTERPRETED_OBJECT:<tag>` | A document object type not converted. | Content of that object is missing; check the original if it matters. |
| `UNRESOLVED_IMAGE_REFERENCE` | An image reference points to no embedded data. | That image is missing from the output. |
| `MISSING_MANIFEST_TARGET:<id>` | An HWPX manifest item points to a missing part. | The referenced image or part is missing. |
| `CELL_ADDRESS_MISSING` | A table cell had no row/column address. | Table layout may be approximate. |
| `TEXT_OUTSIDE_SECTIONS_REQUIRES_REVIEW:<part>` | Text found in an HWPX part outside the body sections. | Not converted; check the original if it matters. |
| `EXTERNAL_BINDATA_LINK_NOT_FETCHED` | The document links an external file. | Linked files are never fetched. |
| `DEFLATE_TRAILING_BYTES_IGNORED` | Extra bytes after a compressed stream were ignored. | Seen in real files; usually harmless. |
| `PYHWP_EXPERIMENTAL_COVERAGE` | Always set for HWP 5 input. | HWP 5 coverage depends on pyhwp; some objects may be missing. |
| `SCRIPTS_PRESENT_NOT_EXECUTED` | The document contains scripts. | They were not executed; nothing to do. |
| `SIGNATURE_NOT_VALIDATED` | The document has a digital signature. | The signature was not checked. |
| `DOCUMENT_HISTORY_NOT_EXTRACTED` | The document stores change history. | Only the current text was converted. |
