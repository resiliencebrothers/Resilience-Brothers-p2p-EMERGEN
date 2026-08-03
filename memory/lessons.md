## Ago 2026 — Race condition en search_replace paralelos sobre el MISMO archivo
Dos veces (OperationDialog.jsx iter115, AssetsView.jsx iter116) al emitir varios search_replace del MISMO archivo en un solo batch paralelo, una edición sobrescribió a la otra (read-modify-write concurrente): la herramienta reporta "successful" pero un cambio (típicamente el de imports) se pierde → ReferenceError en runtime.
REGLA: ediciones a un mismo archivo SIEMPRE secuenciales (batches distintos) o en un único search_replace combinado. Paralelizar solo ediciones de archivos distintos.
