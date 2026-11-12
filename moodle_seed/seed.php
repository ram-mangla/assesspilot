<?php
define('CLI_SCRIPT', true);
$dir = getenv('MOODLE_DIR') ?: '/home/claude/moodle';
require($dir . '/config.php');
require_once($CFG->dirroot . '/course/lib.php');
require_once($CFG->dirroot . '/course/modlib.php');
require_once($CFG->dirroot . '/mod/quiz/locallib.php');
require_once($CFG->dirroot . '/question/editlib.php');
require_once($CFG->dirroot . '/question/format.php');
require_once($CFG->dirroot . '/question/format/xml/format.php');
$admin = get_admin(); \core\session\manager::set_user($admin);

$course = $DB->get_record('course', ['shortname' => 'QL101']) ?: create_course((object)['fullname' => 'Quiz Lab', 'shortname' => 'QL101', 'category' => 1, 'format' => 'topics', 'numsections' => 1]);

function import_qs($xmlfile, $cat, $course) {
    global $DB;
    $before = $DB->get_fieldset_sql("SELECT q.id FROM {question} q");
    $f = new qformat_xml();
    $f->setCategory($cat); $f->setContexts([context::instance_by_id($cat->contextid)]);
    $f->setCourse($course); $f->setFilename($xmlfile); $f->setRealfilename(basename($xmlfile));
    $f->setMatchgrades('nearest'); $f->setCatfromfile(false); $f->setContextfromfile(false); $f->setStoponerror(true);
    ob_start(); $ok = $f->importpreprocess() && $f->importprocess() && $f->importpostprocess(); ob_end_clean();
    if (!$ok) { throw new moodle_exception('importfailed'); }
    $after = $DB->get_fieldset_sql("SELECT q.id FROM {question} q ORDER BY q.id");
    return array_values(array_diff($after, $before));
}

function mkquiz($course, $name, $perpage) {
    $m = new stdClass();
    $m->modulename = 'quiz'; $m->module = $GLOBALS['DB']->get_field('modules', 'id', ['name' => 'quiz']);
    $m->course = $course->id; $m->section = 0; $m->visible = 1; $m->name = $name; $m->intro = ''; $m->introformat = FORMAT_HTML;
    $m->cmidnumber = ''; $m->timeopen = 0; $m->timeclose = 0; $m->timelimit = 0; $m->overduehandling = 'autosubmit'; $m->graceperiod = 0;
    $m->preferredbehaviour = 'deferredfeedback'; $m->canredoquestions = 0; $m->attempts = 0; $m->attemptonlast = 0; $m->grademethod = 1;
    $m->decimalpoints = 2; $m->questiondecimalpoints = -1; $m->questionsperpage = $perpage; $m->navmethod = 'free'; $m->shuffleanswers = 1;
    $m->sumgrades = 0; $m->grade = 10; $m->browsersecurity = '-'; $m->quizpassword = ''; $m->subnet = ''; $m->delay1 = 0; $m->delay2 = 0;
    $m->showuserpicture = 0; $m->showblocks = 0; $m->completion = 0; $m->groupmode = 0; $m->groupingid = 0;
    foreach (['reviewattempt', 'reviewcorrectness', 'reviewmarks', 'reviewspecificfeedback', 'reviewgeneralfeedback', 'reviewrightanswer', 'reviewoverallfeedback'] as $r) { $m->$r = 4368; }
    $m->reviewattempt = 69904;
    $m->feedbacktext = [['text' => '', 'format' => FORMAT_HTML]]; $m->feedbackboundaries = []; 
    return add_moduleinfo($m, $course);
}

$ctx = context_course::instance($course->id);
$cat = question_get_default_category($ctx->id) ?: question_make_default_categories([$ctx]);
foreach ([['Quiz A - one per page', 1], ['Quiz B - all on one page', 0]] as [$name, $pp]) {
    $mi = mkquiz($course, $name, $pp);
    $quiz = $DB->get_record('quiz', ['id' => $mi->instance]);
    $ids = import_qs(__DIR__ . '/questions.xml', $cat, $course);
    foreach ($ids as $qid) { quiz_add_quiz_question($qid, $quiz, 0); }
    quiz_update_sumgrades($quiz);
    foreach (['reviewattempt','reviewcorrectness','reviewmarks','reviewspecificfeedback','reviewgeneralfeedback','reviewrightanswer','reviewoverallfeedback'] as $f) { $DB->set_field('quiz', $f, 4368, ['id' => $quiz->id]); }  // students may see marks right after attempt
    echo "QUIZ $name cmid={$mi->coursemodule} questions=" . count($ids) . "\n";
}
