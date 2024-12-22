import subprocess
import re
import os
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from pathlib import Path

@dataclass
class SourceLineInfo:
    file: str
    line: int
    function: str


@dataclass
class IRAMSection:
    name: str
    address: str
    size: int
    function_name: str
    instructions: List[str]
    source_lines: List[SourceLineInfo]
    string_content: Optional[str] = None  # New field for string content
    data_type: Optional[str] = None      # New field to identify content type


class ESPIRAMAnalyzer:
    def __init__(self, project_path: str, build_dir: str = "build"):
        self.project_path = Path(project_path)
        self.build_dir = self.project_path / build_dir
        self.objdump_path = "xtensa-esp32-elf-objdump"
        self.addr2line_path = "xtensa-esp32-elf-addr2line"
        self.readelf_path = "xtensa-esp32-elf-readelf"  # Added for string analysis
        self.sections: List[IRAMSection] = []
        self.idf_run = str(self.project_path / 'idfRun.sh')

    def _extract_strings_from_section(self, elf_file: str, section: IRAMSection) -> Optional[str]:
        """Extract string content from a section using readelf and objdump."""
        elf_path = self.build_dir / elf_file

        # First try with readelf to get section headers
        cmd = [
            self.idf_run,
            self.readelf_path,
            '-x',  # Hex dump
            section.name,
            str(elf_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.project_path)
        if result.returncode != 0:
            return None

        # Parse the hex dump to look for string content
        hex_content = []
        for line in result.stdout.split('\n'):
            if '0x' in line:
                hex_values = line.split()[1:5]  # Get the hex values
                hex_content.extend(hex_values)

        # Convert hex to ASCII and look for readable strings
        try:
            bytes_content = bytes.fromhex(''.join(hex_content))
            # Try to decode as UTF-8, falling back to ASCII
            try:
                return bytes_content.decode('utf-8')
            except UnicodeDecodeError:
                return bytes_content.decode('ascii', errors='replace')
        except:
            return None

    def _analyze_section_content(self, section: IRAMSection) -> None:
        """Analyze the content type of a section based on its instructions."""
        text_patterns = {
            'string': r'\.string|\.ascii|\.rodata',
            'jump_table': r'jump|branch|table',
            'vector_table': r'vector|interrupt|handler',
        }

        # Analyze instructions to determine content type
        content_type = None
        for instr in section.instructions:
            for type_name, pattern in text_patterns.items():
                if re.search(pattern, instr, re.IGNORECASE):
                    content_type = type_name
                    break
            if content_type:
                break

        section.data_type = content_type or 'code'  # Default to 'code' if no specific type found

    def analyze_file(self, obj_file: str, elf_file: Optional[str] = None) -> List[IRAMSection]:
        """Analyze a specific object file for IRAM sections."""
        """Analyze a specific object file for IRAM sections."""
        if not obj_file.endswith('.obj'):
            obj_file += '.obj'

        file_path = Path(obj_file) if os.path.isabs(obj_file) else self.build_dir / obj_file
        if not file_path.exists():
            raise FileNotFoundError(f"Object file not found: {file_path}")

        # Run objdump
        cmd = [self.idf_run, self.objdump_path, "-d", str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.project_path)

        if result.returncode != 0:
            raise RuntimeError(f"objdump failed: {result.stderr}")

        sections = self._parse_objdump_output(result.stdout)

        # If ELF file is provided, get source line information
        if elf_file:
            for section in sections:
                # Extract addresses from instructions
                addresses = [instr.split(':')[0].strip() for instr in section.instructions]
                section.source_lines = self._get_source_info(elf_file, addresses)

                # Analyze section content type
                self._analyze_section_content(section)

                # Try to extract strings if it seems to contain string data
                if section.data_type == 'string':
                    section.string_content = self._extract_strings_from_section(elf_file, section)

        return sections

    def get_full_report(self, obj_file: str, elf_file: str, map_file: str) -> str:
        """Generate a comprehensive report including string analysis."""
        sections = self.analyze_file(obj_file, elf_file)
        map_info = self.analyze_map_file(map_file)

        report = ["ESP32 IRAM Analysis Report", "=" * 50, ""]

        # Object file analysis with enhanced content information
        report.append("Object File Analysis:")
        report.append("-" * 20)

        for section in sections:
            report.append(f"\nSection: {section.name}")
            report.append(f"Function: {section.function_name}")
            report.append(f"Address: {section.address}")
            report.append(f"Size: {section.size} bytes")
            report.append(f"Content Type: {section.data_type}")

            if section.string_content:
                report.append("\nString Content:")
                report.append("-" * 15)
                report.append(section.string_content)
                report.append("-" * 15)

            if hasattr(section, 'source_lines'):
                report.append("\nSource Locations:")
                for i, (info, instruction) in enumerate(zip(section.source_lines, section.instructions)):
                    report.append(f"  {instruction}")
                    report.append(f"    → {info.file}:{info.line} in {info.function}")

            report.append("-" * 40)

        # Memory usage analysis
        report.append("\nIRAM Memory Usage Analysis:")
        report.append("-" * 25)

        total_size = 0
        by_type = {}

        for section in sections:
            total_size += section.size
            by_type[section.data_type] = by_type.get(section.data_type, 0) + section.size

        report.append(f"\nTotal IRAM Usage: {total_size} bytes")
        report.append("\nUsage by Content Type:")
        for content_type, size in by_type.items():
            percentage = (size / total_size) * 100 if total_size > 0 else 0
            report.append(f"  {content_type}: {size} bytes ({percentage:.1f}%)")

        # Map file analysis (unchanged)
        report.append("\nMap File Analysis:")
        report.append("-" * 20)

        for section_name, info in map_info.items():
            report.append(f"\nSection: {section_name}")
            report.append(f"Base Address: {info['address']}")
            report.append(f"Size: {info['size']} bytes")

            if info['symbols']:
                report.append("\nSymbols:")
                for symbol in info['symbols']:
                    report.append(f"  {symbol['address']}: {symbol['name']}")
                    if symbol['source']:
                        report.append(f"    Source: {symbol['source']}")

        return "\n".join(report)

    def _get_source_info(self, elf_file: str, addresses: List[str]) -> List[SourceLineInfo]:
        """Get source file and line information for a list of addresses."""

        elf_path = self.build_dir / elf_file

        if not elf_path.exists():
            return []

        cmd = [
            self.idf_run,
            self.addr2line_path,
            '-e', str(elf_path),
            '-f',  # Show function names
            '-C',  # Demangle names
            *addresses
        ]

        result = subprocess.run(cmd,
                                capture_output=True,
                                text=True,
                                cwd=self.project_path)

        if result.returncode != 0:
            raise RuntimeError(f"addr2line failed: {result.stderr}")

        lines = result.stdout.strip().split('\n')
        source_info = []

        # addr2line outputs function name and source:line pairs
        for i in range(0, len(lines), 2):
            function = lines[i]
            source_line = lines[i + 1]

            if ':' in source_line:
                file, line = source_line.rsplit(':', 1)
                try:
                    line_num = int(line)
                except ValueError:
                    line_num = 0
            else:
                file = source_line
                line_num = 0

            source_info.append(SourceLineInfo(file, line_num, function))

        return source_info

    def analyze_map_file(self, map_file: str) -> Dict[str, Dict]:
        """Analyze the map file for IRAM sections."""
        if not map_file.endswith('.map'):
            map_file += '.map'

        file_path = Path(map_file) if os.path.isabs(map_file) else self.build_dir / map_file

        if not file_path.exists():
            raise FileNotFoundError(f"Map file not found: {file_path}")

        with open(file_path, 'r') as f:
            content = f.read()

        # Parse IRAM sections from map file
        iram_sections = {}
        current_section = None

        for line in content.split('\n'):
            if '.iram' in line and ' 0x' in line:
                # Example: .iram1.text    0x40080000    0x1234 : AT (0x3f400000)
                parts = line.split()
                if len(parts) >= 3:
                    section_name = parts[0]
                    address = parts[1]
                    size = int(parts[2], 16)
                    current_section = section_name
                    iram_sections[current_section] = {
                        'address': address,
                        'size': size,
                        'symbols': []
                    }
            elif current_section and ' 0x' in line and ')' in line:
                # Example: 0x40080000    function_name    /path/to/source.c:123
                parts = line.split()
                if len(parts) >= 2:
                    addr = parts[0]
                    symbol = parts[1]
                    source_info = ' '.join(parts[2:]) if len(parts) > 2 else ''
                    iram_sections[current_section]['symbols'].append({
                        'address': addr,
                        'name': symbol,
                        'source': source_info
                    })

        return iram_sections

    def _parse_objdump_output(self, output: str) -> List[IRAMSection]:
        """Parse objdump output to extract IRAM sections."""
        sections = []
        current_section = None
        current_instructions = []

        # Regular expressions for parsing
        section_pattern = r"Disassembly of section \.iram\d+\.(\d+):"
        function_pattern = r"[\da-f]+ <(.+)>:"
        instruction_pattern = r"\s*([\da-f]+):\s+([\da-f]+)\s+(.+)"

        for line in output.split('\n'):
            # Check for new section
            section_match = re.match(section_pattern, line)
            if section_match:
                if current_section:
                    current_section.instructions = current_instructions
                    sections.append(current_section)
                current_section = IRAMSection(
                    name=f".iram{section_match.group(1)}",
                    address="",
                    size=0,
                    function_name="",
                    instructions=[],
                    source_lines=[]
                )
                current_instructions = []
                continue

            # Check for function name
            function_match = re.match(function_pattern, line)
            if function_match and current_section:
                current_section.function_name = function_match.group(1)
                continue

            # Check for instruction
            instruction_match = re.match(instruction_pattern, line)
            if instruction_match and current_section:
                addr, opcode, instr = instruction_match.groups()
                if not current_section.address:
                    current_section.address = addr
                current_instructions.append(f"{addr}: {opcode} {instr}")
                current_section.size += len(bytes.fromhex(opcode))

        # Add last section if exists
        if current_section:
            current_section.instructions = current_instructions
            sections.append(current_section)

        return sections


if __name__ == "__main__":
    proj_path = "/Users/riccardo/Sources/GitHub/hello.esp32/hello-idf"
    analyzer = ESPIRAMAnalyzer(proj_path)

    # Paths to analyze
    obj_file = "esp-idf/wasm3/CMakeFiles/__idf_wasm3.dir/wasm3/m3_compile.c.obj"
    elf_file = "hello-idf.elf"
    map_file = "hello-idf.map"

    output = analyzer.get_full_report(obj_file, elf_file, map_file)

    #print(output)

    # Apri il file in modalità scrittura
    file = open("iram-output.txt", "w")

    # Scrivi la stringa nel file
    file.write(output)

    # Chiudi il file
    file.close()