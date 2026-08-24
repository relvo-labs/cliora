#!/usr/bin/env node

import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, relative, extname } from "node:path";

function parseArgs(argv) {
  const options = { root: process.cwd(), allowFallback: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--allow-fallback") {
      options.allowFallback = true;
    } else if (argument === "--root") {
      options.root = resolve(argv[++index] ?? "");
    } else {
      throw new Error(`unknown argument: ${argument}`);
    }
  }
  return options;
}

function filesBelow(directory) {
  const files = [];
  for (const entry of readdirSync(directory)) {
    const path = resolve(directory, entry);
    if (statSync(path).isDirectory()) files.push(...filesBelow(path));
    else files.push(path);
  }
  return files;
}

function lineAt(source, offset) {
  return source.slice(0, offset).split("\n").length;
}

function vueCss(source) {
  const regions = [];
  const styleBlock = /<style(?:\s[^>]*)?>([\s\S]*?)<\/style>/gi;
  for (const match of source.matchAll(styleBlock)) {
    const body = match[1] ?? "";
    regions.push({ source: body, offset: (match.index ?? 0) + match[0].indexOf(body) });
  }
  const template = source.match(/<template(?:\s[^>]*)?>([\s\S]*?)<\/template>/i);
  if (template) {
    const body = template[1] ?? "";
    const templateOffset = (template.index ?? 0) + template[0].indexOf(body);
    const literalStyle = /\sstyle\s*=\s*(["'])(.*?)\1/gi;
    for (const match of body.matchAll(literalStyle)) {
      const value = match[2] ?? "";
      regions.push({
        source: value,
        offset: templateOffset + (match.index ?? 0) + match[0].indexOf(value),
      });
    }
  }
  return regions;
}

// Comments are blanked, not removed: every remaining character keeps its offset, so the
// line numbers this reports still point at the right line.
//
// **This exists because the checker matched its own explanation.** A comment saying "a
// `var(--cell-tone)` here would be unresolvable" was reported as an unresolvable
// `var(--cell-tone)`, and the cheapest way to green that is to delete the sentence saying
// why the rule exists — the failure `plan/18/09` §3 item 15 records for three V2.2 gates.
function withoutComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, (comment) =>
    comment.replace(/[^\n]/g, " "),
  );
}

function references(source, offset = 0) {
  const found = [];
  const variable = /var\(\s*(--[a-z0-9-]+)(\s*,[^)]*)?\s*\)/gi;
  for (const match of withoutComments(source).matchAll(variable)) {
    found.push({
      name: match[1],
      fallback: Boolean(match[2]),
      expression: match[0],
      offset: offset + (match.index ?? 0),
    });
  }
  return found;
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const src = resolve(options.root, "frontend/src");
  const tokenFiles = [
    resolve(src, "theme/tokens.css"),
    resolve(src, "theme/base.css"),
  ];
  const defined = new Set();
  for (const path of tokenFiles) {
    const source = readFileSync(path, "utf8");
    for (const match of source.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gim)) {
      defined.add(match[1]);
    }
  }

  // Intentionally empty. Runtime or third-party variables may be added only with a
  // comment naming the code that owns the definition (plan/19/07 §3.2).
  const allowlist = new Set([]);
  const problems = [];
  for (const path of filesBelow(src)) {
    const extension = extname(path);
    if (![".vue", ".css", ".ts"].includes(extension)) continue;
    const source = readFileSync(path, "utf8");
    const regions = extension === ".vue" ? vueCss(source) : [{ source, offset: 0 }];
    for (const region of regions) {
      for (const reference of references(region.source, region.offset)) {
        if (defined.has(reference.name) || allowlist.has(reference.name)) continue;
        problems.push({
          ...reference,
          file: relative(options.root, path),
          line: lineAt(source, reference.offset),
        });
      }
    }
  }

  for (const problem of problems) {
    const level = problem.fallback ? "WARN " : "ERROR";
    const consequence = problem.fallback
      ? "繞過 token，實際使用 fallback"
      : "宣告會被丟棄";
    console.error(
      `${level}  ${problem.file}:${problem.line}  ${problem.expression}  ${consequence}`,
    );
    if (problem.name.startsWith("--color-")) {
      console.error(
        "       tokens.css 沒有 --color-* 命名空間；請使用 --surface- / --text- / --border- / --action- / --status-。",
      );
    }
  }

  const errors = problems.filter((problem) => !problem.fallback).length;
  const warnings = problems.length - errors;
  if (problems.length === 0) {
    console.log(`Token references: OK (${defined.size} definitions, 0 problems)`);
  } else {
    console.error(`Token references: ${errors} ERROR, ${warnings} WARN`);
  }
  process.exitCode = errors > 0 || (warnings > 0 && !options.allowFallback) ? 1 : 0;
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 2;
}
