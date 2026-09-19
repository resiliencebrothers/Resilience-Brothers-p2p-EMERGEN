/**
 * Guardia contra extensiones que mutan el DOM (Google Translate del navegador,
 * etc.). Translate envuelve los nodos de texto en <font> y React, al
 * reconciliar, llama removeChild/insertBefore sobre nodos que ya no son hijos
 * directos → NotFoundError → pantalla "Algo salió mal" (facebook/react#11538).
 * El parche ignora esas dos llamadas imposibles en lugar de dejar caer la app.
 */
if (typeof Node === "function" && Node.prototype) {
  const originalRemoveChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function removeChildSafe(child) {
    if (child && child.parentNode !== this) {
      if (window.console) {
        console.warn("removeChild ignorado: nodo movido por una extensión del navegador (¿Google Translate?)");
      }
      return child;
    }
    return originalRemoveChild.apply(this, arguments);
  };
  const originalInsertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function insertBeforeSafe(newNode, referenceNode) {
    if (referenceNode && referenceNode.parentNode !== this) {
      if (window.console) {
        console.warn("insertBefore ignorado: nodo movido por una extensión del navegador (¿Google Translate?)");
      }
      return newNode;
    }
    return originalInsertBefore.apply(this, arguments);
  };
}
