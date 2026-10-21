# Document images in retrieval and answers

The behavior below was agreed in the design conversation and implemented for
new PDF uploads to the web library.

## Agreed behavior

- The first version supports images in PDF documents.
- Apply image support to new PDF uploads. Existing library files are outside
  this work and require no backfill or reprocessing.
- Show a thumbnail of a cited image in its source, with an option to enlarge it.
- Retain generated image descriptions to help text search find relevant images.
- Preserve the original document image and its association with supporting text.
- Give the answer model retrieved original text and the corresponding original
  images. Generated image descriptions are used for retrieval, not supplied as
  evidence in the answer request.
- Send the specific figure when its association with the retrieved text is
  clear. If the association is ambiguous, send an image of the original PDF
  page and identify the source as a page, not a confidently linked figure.
  If the relationship remains unclear after reading the page, state that
  uncertainty in the answer rather than inventing an association.
- Original images are the evidence for visual details. Do not infer unreadable
  details from a generated description.
- A failure processing an individual image does not discard usable document
  text or successfully processed images. Surface incomplete image processing
  to the user. Fail the document normally if no usable evidence remains.
- If description generation fails but the image and its text association are
  available, retain the image for retrieval through its associated text. A
  missing description does not prevent the answer model from reading it.

## Implementation

- New PDF uploads opt into visuals through a durable library flag. Existing
  records default to text-only processing; no existing corpus is reprocessed.
- PyMuPDF finds embedded raster images and groups vector drawings by geometry.
  Crops and fallback pages are rendered from the original PDF as JPEG assets
  under `web_data_dir/images/`, addressed by UUID. Long edges are limited to
  2000 pixels. Dense layouts with more than ten regions and full-page scans use
  the whole page, as do rotated visual pages. Vector crops include a margin
  for nearby axis labels. The uploaded PDF itself remains available for download.
- The configured `agent_model` describes visuals once during training, using
  the saved OpenAI key and `store=False`. It must support image inputs. Local
  OCR selects text extraction; descriptions and answers still use OpenAI.
- A proposed anchor must occur in one original chunk and one native PDF text
  line, in the same column and within 96 PDF points of its figure. It must
  also be unambiguously nearer this figure than competing regions. Otherwise
  the visual source is the full page.
- Description nodes are indexed by FAISS/BM25 and evaluated by the local
  reranker. After ranking, retrieval returns their original supporting text
  and image references. Description text and internal metadata never enter
  the answer request, source dialog, or saved conversation.
- Answer requests attach deduplicated JPEG image data with citation labels;
  sources retain the same image references. Missing assets are marked
  unavailable and are never replaced with generated descriptions as evidence.
- Source image URLs are scoped to an indexed chunk. Removal of indexing or
  deletion revokes access and removes unreferenced assets. Publication failures,
  cancellation, retries, and startup recovery also prune unpublished assets.
- Partial image-processing warnings are persisted with the indexed nodes and
  displayed in the library. A failed crop falls back to the page; a failed
  description retains the page and its original text as usable evidence.

## Validation

- Tests use real PDF images/vector drawings/scans and temporary FAISS indexes,
  with mocked OpenAI HTTP responses and local embedding/reranker fixtures.
- Cover text-image association, competing columns, ambiguous and invalid
  anchors, visual-only retrieval, exclusion of descriptions from answer inputs,
  real image bytes, deduplication, legacy records/database upgrade, partial
  failures, cancellation, restart, removal, deletion, and access isolation.
- The disposable `tests/visual_browser_fixture.py` serves a saved visual source
  on port 8003 for browser verification without live API calls.
