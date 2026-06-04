# SmartSchool Israel - Home Assistant Integration

Home Assistant custom integration for SmartSchool Israel (webtopserver.smartschool.co.il).

## Key Features

- **Multiple Students Support**: Automatically discovers all children in parent account
- **Homework Tracking**: See all homework assignments with dates and descriptions
- **Grades Monitoring**: Track latest grades and calculate averages
- **Behavior Events**: Monitor positive/negative behavior events
- **Schedule Calendar**: Weekly lesson schedule with teacher info and homework
- **Next Lesson Sensor**: Know what's coming up next

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/alexpekurovsky/hass-smartschool-integration`
6. Select category "Integration"
7. Click "Add"
8. Search for "SmartSchool Israel" in HACS
9. Click "Download"
10. Restart Home Assistant

### Manual

1. Download the latest release from [GitHub](https://github.com/alexpekurovsky/hass-smartschool-integration/releases)
2. Extract and copy the `custom_components/smartschool_il` folder to your Home Assistant `custom_components` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **SmartSchool Israel**
4. Enter your SmartSchool username and password
5. Click Submit

The integration will automatically discover all students and create entities for each.

## Entities Created

For each student, the following entities are created:

### Sensors

- **Homework Count**: Number of homework assignments (with list in attributes)
- **Latest Grade**: Date of most recent grade (grade value in attributes)
- **Grade Average**: Average of all grades
- **Behavior Events**: Count of behavior events (with details in attributes)
- **Next Lesson**: Name of the next upcoming lesson

### Calendar

- **Schedule**: Weekly lesson schedule with times, teachers, and homework (📝 emoji indicates homework)

### Todo List

- **Homework**: Interactive todo list of all homework assignments with due dates
  - Check off items as complete
  - Items persist until removed from school system
  - Completion state is saved locally

## Advanced Configuration

### Lesson Times

Each student can have their own lesson schedule configured:

1. Go to **Settings** → **Devices & Services** → **SmartSchool Israel**
2. Click **Configure**
3. Select the student
4. Set custom lesson times for lessons 1-9 (format: HH:MM-HH:MM)

This is useful when children attend different schools with different schedules.

## Features

- ✅ **Per-Student Configuration**: Different lesson times for each child
- ✅ **Hebrew Support**: Device names show both numeric and Hebrew grade notation (e.g., "Class 3-1 (ג1)")
- ✅ **Smart Timezone Handling**: Uses Home Assistant's configured timezone
- ✅ **Auto-Refresh**: Automatically fetches new data every 30 minutes
- ✅ **Dynamic Study Year**: Automatically handles Israeli school year transitions (September to August)
- ✅ **Persistent Completion**: Homework completion state survives restarts

## Device Structure

Each student is represented as a Device with:
- **Name**: Student's full name
- **Model**: Current class (e.g., "Class 3-1")
- **Manufacturer**: SmartSchool Israel
- **Suggested Area**: School

All sensors and calendar for a student are grouped under their device.

## Data Update

The integration updates data every 30 minutes by default. It fetches:
- Current week + 3 weeks ahead for schedule
- Latest grades
- Recent behavior events

## Lesson Schedule

Default lesson times (can be adjusted via integration options):
- Hour 1: 8:00 - 8:50
- Hour 2: 8:50 - 9:35
- Hour 3: 10:05 - 10:55
- Hour 4: 10:55 - 11:45
- Hour 5: 11:55 - 12:40
- Hour 6: 12:40 - 13:30

To customize lesson times:
1. Go to **Settings** → **Devices & Services** → **SmartSchool Israel**
2. Click **Configure**
3. Adjust the lesson times as needed

## Dashboard Example

A complete dashboard example is provided in [`dashboard_example.yaml`](dashboard_example.yaml).

To use it:
1. Go to **Settings** → **Dashboards**
2. Create a new dashboard or edit an existing one
3. Add a new view
4. Copy the content from `dashboard_example.yaml` and paste it into the RAW configuration editor
5. Replace `student_name` with your student's entity name(s)

The example dashboard includes:
- **Summary cards** - Homework count, grade average, behavior events
- **Next lesson** - Shows what's coming up next
- **Today's schedule** - Calendar view of today's lessons
- **Homework list** - Table with all homework assignments and dates
- **Latest grade** - Most recent grade with subject and details
- **Weekly schedule** - Full week calendar view

## Example Automations

### Homework Reminder
```yaml
automation:
  - alias: "Homework Reminder"
    trigger:
      - platform: time
        at: "16:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.student_name_homework_count
        above: 0
    action:
      - service: notify.mobile_app
        data:
          message: "Your student has {{ states('sensor.student_name_homework_count') }} homework items to complete"
```

### New Grade Alert
```yaml
automation:
  - alias: "New Grade Alert"
    trigger:
      - platform: state
        entity_id: sensor.student_name_latest_grade
    action:
      - service: notify.family
        data:
          message: "New grade received: {{ states('sensor.student_name_latest_grade') }}"
```

## Troubleshooting

### Login Failed
- Verify your username and password are correct
- Check that you can log in at webtopserver.smartschool.co.il
- Look at Home Assistant logs for detailed error messages

### No Students Found
- Ensure your account is a parent account with linked children
- Check Home Assistant logs for API errors

### Calendar Not Showing Events
- Verify the hour time mappings in `const.py` match your school's schedule
- Check that schedule data is being fetched in the logs

## Support

For issues and feature requests, please open an issue on GitHub.

## Credits

Developed for Home Assistant integration with SmartSchool Israel.
