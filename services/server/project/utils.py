"""
General utility functions for the ESG project.
"""


def join_path(*parts):
    """
    Safely join path parts, handling leading/trailing slashes consistently.
    This is a general-purpose path joining function that normalizes slashes
    and handles edge cases for mixed path operations.

    Args:
        *parts: Path components to join

    Returns:
        str: Properly joined path with forward slashes

    Examples:
        join_path('dir', 'subdir', 'file.txt') -> 'dir/subdir/file.txt'
        join_path('/root', 'dir/') -> '/root/dir'
        join_path('', 'dir', '', 'file') -> 'dir/file'
    """
    if not parts:
        return ""

    # Filter out empty parts and normalize slashes
    clean_parts = []
    for part in parts:
        if part:
            # Convert backslashes to forward slashes and strip leading/trailing slashes
            normalized = str(part).replace('\\', '/').strip('/')
            if normalized:  # Only add non-empty parts
                clean_parts.append(normalized)

    if not clean_parts:
        return ""

    # Join with forward slashes
    result = '/'.join(clean_parts)

    # If the first original part started with '/', preserve that
    if str(parts[0]).startswith('/'):
        result = '/' + result

    return result