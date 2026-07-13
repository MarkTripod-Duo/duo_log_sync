import * as core from "@actions/core";
import * as fs from "fs";
import * as path from "path";
import { parseStringPromise } from "xml2js";

function extractFailureLocation(
  failureText: string,
  testFile: string,
): { file: string; line: number } | null {
  // Find any "<something>.py:LINE" in traceback that matches this repo's file
  const regex = /([^\s:]+\.py):(\d+):/g;
  let match;
  let lastMatch = null;

  while ((match = regex.exec(failureText)) !== null) {
    // Prefer matches in the same file as the test OR under repo paths
    if (match[1] === testFile || fs.existsSync(match[1])) {
      lastMatch = match;
    }
  }

  if (lastMatch) {
    return { file: lastMatch[1], line: parseInt(lastMatch[2], 10) };
  }
  return null;
}

function preserveIndent(message: string): string {
  return message
    .split("\n")
    .map((line) =>
      line.replace(/^([ \t]+)/, (l: string) =>
        l.replace(/ /g, "\u00A0").replace(/\t/g, "\u00A0\u00A0\u00A0\u00A0"),
      ),
    )
    .join("\n");
}

function extractAssertionBlock(failureText: string) {
  const lines = failureText.split("\n");
  let startIdx = -1;

  for (let i = lines.length - 1; i >= 0; i--) {
    core.debug("(1) " + i + ": " + lines[i]);
    if (lines[i].trimStart().startsWith("E       AssertionError")) {
      startIdx = i;
      break;
    }
  }

  if (startIdx === -1) {
    return preserveIndent(failureText.trim());
  }

  const collected: string[] = [];
  for (let j = startIdx; j < lines.length; j++) {
    core.debug("(2) " + j + ": " + lines[j]);
    if (lines[j].trimStart().startsWith("E") || lines[j].trim() === "") {
      collected.push(lines[j]);
    } else {
      break;
    }
  }

  const joined = collected.join("\n");
  return preserveIndent(joined);
}

async function run(): Promise<void> {
  try {
    const filePath = core.getInput("file", { required: true });
    const absPath = path.resolve(filePath);

    if (!fs.existsSync(absPath)) {
      core.setFailed(`JUnit XML file not found: ${absPath}`);
      return;
    }

    const xmlData = fs.readFileSync(absPath, "utf8");
    let result;
    try {
      result = await parseStringPromise(xmlData);
    } catch (err) {
      core.setFailed(`Invalid XML in ${absPath}: ${err}`);
      return;
    }

    // JUnit XML format often: testsuites > testsuite > testcase
    const testSuites = result.testsuites?.testsuite || result.testsuite;
    if (!testSuites) {
      core.info("No <testsuite> elements found in report.");
      return;
    }

    const suites = Array.isArray(testSuites) ? testSuites : [testSuites];

    let annotations = 0;

    for (const suite of suites) {
      const testCases = suite.testcase || [];
      for (const tc of testCases) {
        const name = tc.$?.name;
        const classname = tc.$?.classname || null;
        let file = tc.$?.file;
        // The line in the test case is NOT the failure line, it's the line
        // where the test case is defined. We need to parse the failure
        // message to get the line of failure.
        let line = tc.$?.line;

        const failures = tc.failure || tc.error || [];
        if (failures.length > 0) {
          for (const failure of failures) {
            const message = (
              failure._ ||
              failure.$?.message ||
              "Test failed"
            ).trim();
            const loc = extractFailureLocation(message, file);
            if (loc) {
              file = loc.file;
              line = loc.line;
            }
            let err = `Failed ${name}`;
            if (classname) {
              err = `Failed ${classname}:${name}`;
            }
            core.debug(
              `${file},${line},${classname},${name},` + JSON.stringify(message),
            );
            const formatted = extractAssertionBlock(message);
            core.error(formatted, {
              title: err,
              file: file,
              startLine: line,
            });
            annotations++;
          }
        }
      }
    }

    core.info(`Published ${annotations} annotations from ${filePath}`);
  } catch (error) {
    core.setFailed((error as Error).message);
  }
}

run();
