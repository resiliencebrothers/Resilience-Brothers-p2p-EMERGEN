/**
 * Custom ESLint rule: no-dialog-without-scroll
 *
 * Rationale: on 10 Feb 2026 an admin reported that the "Editar/Nueva Moneda"
 * modal on production hid its Guardar button on a smaller laptop screen — the
 * Radix DialogContent had no `max-h` cap, so any content taller than the
 * viewport was silently truncated with no scrollbar.
 *
 * We swept 13 modals and added `max-h-[85vh] overflow-y-auto`. This rule
 * prevents that regression from ever coming back: any new `<DialogContent>`
 * that ships without a `max-h-` utility in its className will fail lint.
 *
 * Notes:
 * - Detects both static string classNames and template literals.
 * - Skips DialogContent that explicitly opts out with `overflow-hidden`
 *   (used by hero-image wizards like OnboardingDialog) OR `className="hidden"`
 *   (placeholders like TransactionDetailModal).
 * - We only care about the component named `DialogContent` (Radix/shadcn).
 */
"use strict";

/** @type {import('eslint').Rule.RuleModule} */
const rule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Require a `max-h-*` utility on <DialogContent className=…> to guarantee scroll on short viewports.",
    },
    schema: [],
    messages: {
      missingMaxH:
        "DialogContent must include a `max-h-[...vh]` (or `max-h-*`) utility in its className, otherwise long forms overflow the viewport on small screens. Suggested: `max-h-[85vh] overflow-y-auto`.",
      missingClassName:
        "DialogContent must have a className with `max-h-[...vh] overflow-y-auto`. Add className=\"max-h-[85vh] overflow-y-auto\" (merge with your other classes).",
    },
  },

  create(context) {
    // Pull the class-string(s) out of a JSX className attribute value.
    // Returns an array of literal strings we can search for `max-h-`.
    function extractClassStrings(valueNode) {
      if (!valueNode) return [];
      // className="foo bar"
      if (valueNode.type === "Literal" && typeof valueNode.value === "string") {
        return [valueNode.value];
      }
      // className={"foo bar"} or className={`foo bar`}
      if (valueNode.type === "JSXExpressionContainer") {
        const expr = valueNode.expression;
        if (expr.type === "Literal" && typeof expr.value === "string") {
          return [expr.value];
        }
        if (expr.type === "TemplateLiteral") {
          // Concatenate all static quasis (dynamic ${…} parts are ignored, they
          // may or may not add max-h — we can't know statically, so we treat
          // the static portion as the source of truth).
          return expr.quasis.map((q) => q.value.cooked || "");
        }
        // clsx / cn(…) etc — collect any inner string literals we can see so
        // devs using helpers still get coverage.
        if (expr.type === "CallExpression") {
          const strings = [];
          const walk = (n) => {
            if (!n) return;
            if (n.type === "Literal" && typeof n.value === "string") {
              strings.push(n.value);
            } else if (n.type === "TemplateLiteral") {
              n.quasis.forEach((q) => strings.push(q.value.cooked || ""));
            } else if (n.type === "ArrayExpression") {
              n.elements.forEach(walk);
            } else if (n.type === "ObjectExpression") {
              n.properties.forEach((p) => {
                // { 'max-h-[85vh]': cond } — the key is meaningful for tailwind
                if (p.key && p.key.type === "Literal") strings.push(String(p.key.value));
                if (p.key && p.key.type === "Identifier") strings.push(p.key.name);
              });
            }
          };
          expr.arguments.forEach(walk);
          return strings;
        }
      }
      return [];
    }

    return {
      JSXOpeningElement(node) {
        // Match only <DialogContent …> (JSX component name).
        if (
          !node.name ||
          node.name.type !== "JSXIdentifier" ||
          node.name.name !== "DialogContent"
        ) {
          return;
        }

        const classNameAttr = node.attributes.find(
          (a) => a.type === "JSXAttribute" && a.name && a.name.name === "className",
        );

        if (!classNameAttr) {
          context.report({ node, messageId: "missingClassName" });
          return;
        }

        const strings = extractClassStrings(classNameAttr.value);
        const joined = strings.join(" ");

        // Opt-outs — designs that intentionally clip.
        if (/\boverflow-hidden\b/.test(joined)) return;
        if (/^\s*hidden\s*$/.test(joined)) return; // placeholder modals

        // Success: any max-h-* class present.
        if (/\bmax-h-\[[^\]]+\]|\bmax-h-\w+/.test(joined)) return;

        context.report({ node: classNameAttr, messageId: "missingMaxH" });
      },
    };
  },
};

export default {
  rules: {
    "no-dialog-without-scroll": rule,
  },
};
