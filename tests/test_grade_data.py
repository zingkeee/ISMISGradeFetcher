import unittest
from pathlib import Path

from grade_data import resolve_data_dir, validate_grades_data


class ValidateGradesDataTests(unittest.TestCase):
    def test_accepts_current_object_schema(self):
        data = {
            "overall": {"gwa": "1.75"},
            "terms": [{"term": "FIRST SEMESTER - 2024", "courses": [{"FG": "1.5"}], "summary": None}],
        }
        self.assertIsNone(validate_grades_data(data))

    def test_accepts_legacy_terms_array(self):
        self.assertIsNone(validate_grades_data([{"term": "Summer 2024", "courses": [], "summary": None}]))

    def test_rejects_missing_terms(self):
        with self.assertRaisesRegex(ValueError, "terms"):
            validate_grades_data({"overall": {"gwa": "1.75"}})

    def test_rejects_invalid_course_rows(self):
        data = {"terms": [{"term": "Fall", "courses": ["not a course row"]}]}
        with self.assertRaisesRegex(ValueError, "courses"):
            validate_grades_data(data)


class ResolveDataDirTests(unittest.TestCase):
    def test_uses_explicit_data_directory(self):
        result = resolve_data_dir({"GRADE_FETCHER_DATA_DIR": "C:/private/grades"}, home=Path("/home/test"), system="nt")
        self.assertEqual(result, Path("C:/private/grades"))

    def test_uses_local_appdata_on_windows(self):
        result = resolve_data_dir({"LOCALAPPDATA": "C:/Users/test/AppData/Local"}, home=Path("/home/test"), system="nt")
        self.assertEqual(result, Path("C:/Users/test/AppData/Local/GradeFetcher"))

    def test_uses_xdg_data_home_on_unix(self):
        result = resolve_data_dir({"XDG_DATA_HOME": "/home/test/.local/share"}, home=Path("/home/test"), system="Linux")
        self.assertEqual(result, Path("/home/test/.local/share/grade-fetcher"))


if __name__ == "__main__":
    unittest.main()
