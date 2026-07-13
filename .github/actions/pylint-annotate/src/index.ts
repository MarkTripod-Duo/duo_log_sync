import * as core from "@actions/core";
import * as fs from "fs";
import * as path from "path";

type PylintMessage = {
  type: string;
  path: string;
  line: number;
  column?: number;
  message: string;
  symbol?: string;
};

function run(): void {
  try {
    const filePath = core.getInput("file", { required: true });
    const absPath = path.resolve(filePath);

    if (!fs.existsSync(absPath)) {
      core.setFailed(`File not found: ${absPath}`);
      return;
    }

    const rawData = fs.readFileSync(absPath, "utf8");
    let items: PylintMessage[];
    try {
      items = JSON.parse(rawData);
    } catch (err) {
      core.setFailed(`Invalid JSON in ${absPath}: ${err}`);
      return;
    }

    const severityMap: Record<string, "error" | "warning" | "notice"> = {
      error: "error",
      fatal: "error",
      warning: "warning",
      convention: "notice",
      refactor: "notice",
      info: "notice",
    };

    for (const msg of items) {
      const sev = severityMap[msg.type] || "notice";
      const msgText = `${msg.message}${msg.symbol ? ` (${msg.symbol})` : ""}`;
      const col = msg.column ?? 1;

      // GitHub Actions workflow command
      // NOTE: console.log is how workflow commands are emitted for annotation
      console.log(
        `::${sev} file=${msg.path},line=${msg.line},col=${col}::${msgText}`,
      );
    }
  } catch (error) {
    core.setFailed((error as Error).message);
  }
}

run();
