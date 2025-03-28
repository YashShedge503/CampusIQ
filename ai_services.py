import re
import string
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

# Setup logging
logger = logging.getLogger(__name__)

# Initialize NLTK components
try:
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)
    nltk.download('wordnet', quiet=True)
except Exception as e:
    logger.warning(f"Could not download NLTK data: {e}")

# Initialize lemmatizer and stopwords
lemmatizer = WordNetLemmatizer()
try:
    stop_words = set(stopwords.words('english'))
except:
    # Fallback if NLTK data download failed
    stop_words = set([
        'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours',
        'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her', 'hers',
        'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
        'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those', 'am', 'is', 'are',
        'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does',
        'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until',
        'while', 'of', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into',
        'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down',
        'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here',
        'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more',
        'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 'should', 'now'
    ])

def preprocess_text(text):
    """Preprocess text by removing punctuation, lowercase, tokenizing, removing stopwords, and lemmatizing."""
    if not text or not isinstance(text, str):
        return ""
    
    # Convert to lowercase and remove punctuation
    text = text.lower()
    text = re.sub(f'[{string.punctuation}]', ' ', text)
    
    # Tokenize and remove stopwords
    tokens = word_tokenize(text)
    tokens = [token for token in tokens if token not in stop_words]
    
    # Lemmatize tokens
    lemmatized_tokens = [lemmatizer.lemmatize(token) for token in tokens]
    
    return ' '.join(lemmatized_tokens)

def calculate_similarity(text1, text2):
    """Calculate cosine similarity between two texts."""
    if not text1 or not text2:
        return 0.0
    
    # Preprocess texts
    processed_text1 = preprocess_text(text1)
    processed_text2 = preprocess_text(text2)
    
    if not processed_text1 or not processed_text2:
        return 0.0
    
    # Create TF-IDF vectors
    vectorizer = TfidfVectorizer()
    try:
        tfidf_matrix = vectorizer.fit_transform([processed_text1, processed_text2])
        
        # Calculate cosine similarity
        similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        return float(similarity)  # Convert numpy.float to Python float
    except Exception as e:
        logger.error(f"Error calculating similarity: {e}")
        return 0.0

def analyze_submission(submission_text, assignment_instructions, rubric=None, reference_answer=None):
    """
    Analyze a student submission against assignment instructions and optionally a rubric or reference answer.
    
    Args:
        submission_text (str): The text of the student's submission
        assignment_instructions (str): The instructions for the assignment
        rubric (str, optional): Rubric text with grading criteria
        reference_answer (str, optional): A reference or model answer
        
    Returns:
        dict: Analysis results including score recommendation and feedback
    """
    if not submission_text or not assignment_instructions:
        return {
            'score_recommendation': None,
            'confidence': 0.0,
            'feedback': "Cannot analyze empty submission or missing assignment instructions.",
            'key_points': [],
            'improvement_areas': []
        }
    
    try:
        # Analyze submission
        analysis_results = {}
        
        # Calculate basic metrics
        word_count = len(submission_text.split())
        analysis_results['word_count'] = word_count
        
        # Check keyword coverage
        # Extract key terms from instructions
        instruction_words = preprocess_text(assignment_instructions).split()
        # Get frequency of most common words in instructions
        instruction_keywords = [word for word, count in Counter(instruction_words).most_common(10)]
        
        # Process submission
        processed_submission = preprocess_text(submission_text)
        submission_words = set(processed_submission.split())
        
        # Calculate keyword coverage
        keywords_found = [keyword for keyword in instruction_keywords if keyword in submission_words]
        keyword_coverage = len(keywords_found) / len(instruction_keywords) if instruction_keywords else 0
        analysis_results['keyword_coverage'] = keyword_coverage
        
        # Calculate similarity to reference answer if provided
        if reference_answer:
            similarity_to_reference = calculate_similarity(submission_text, reference_answer)
            analysis_results['similarity_to_reference'] = similarity_to_reference
        else:
            similarity_to_reference = None
        
        # Extract key points from submission
        key_points = []
        sentences = re.split(r'[.!?]', submission_text)
        for sentence in sentences:
            if len(sentence.strip()) > 10:  # Skip very short sentences
                # Simple heuristic: sentences with keywords are likely key points
                if any(keyword in preprocess_text(sentence) for keyword in instruction_keywords):
                    key_points.append(sentence.strip())
        
        # Limit to top 3 key points
        key_points = key_points[:3]
        analysis_results['key_points'] = key_points
        
        # Identify improvement areas
        improvement_areas = []
        
        # Check for wordiness
        if word_count < 50:
            improvement_areas.append("The submission is quite brief. Consider providing more detailed explanations.")
        elif word_count > 1000:
            improvement_areas.append("The submission is lengthy. Consider being more concise while maintaining key points.")
        
        # Check keyword coverage
        if keyword_coverage < 0.5:
            improvement_areas.append("The submission may not adequately address all required topics from the instructions.")
        
        # Generate score recommendation
        score_factors = [
            keyword_coverage * 0.7,  # Weight keyword coverage highly
        ]
        
        if similarity_to_reference is not None:
            score_factors.append(similarity_to_reference * 0.8)  # Weight similarity to reference answer if available
        
        # Basic score calculation
        if score_factors:
            avg_score = sum(score_factors) / len(score_factors)
            # Scale to 0-100
            score_recommendation = min(100, max(0, avg_score * 100))
        else:
            score_recommendation = None
        
        # Calculate confidence
        if similarity_to_reference is not None:
            confidence = 0.7  # Higher confidence with reference answer
        else:
            confidence = 0.5  # Lower confidence without reference
        
        # Generate feedback
        feedback = []
        if score_recommendation is not None:
            if score_recommendation >= 90:
                feedback.append("Excellent work! The submission thoroughly addresses the assignment requirements.")
            elif score_recommendation >= 80:
                feedback.append("Good work. The submission addresses most of the key points from the assignment.")
            elif score_recommendation >= 70:
                feedback.append("Satisfactory work. The submission addresses the basic requirements but could be improved.")
            else:
                feedback.append("The submission needs significant improvement to fully address the assignment requirements.")
        
        # Add specific feedback about keyword coverage
        if keyword_coverage >= 0.8:
            feedback.append("Excellent coverage of important concepts from the assignment.")
        elif keyword_coverage >= 0.6:
            feedback.append("Good coverage of concepts, but some important ideas may be missing or underdeveloped.")
        else:
            feedback.append("Several important concepts from the assignment instructions are not adequately addressed.")
        
        # Return final analysis results
        return {
            'score_recommendation': score_recommendation,
            'confidence': confidence,
            'feedback': " ".join(feedback),
            'key_points': key_points,
            'improvement_areas': improvement_areas,
            'metrics': {
                'word_count': word_count,
                'keyword_coverage': keyword_coverage,
                'similarity_to_reference': similarity_to_reference
            }
        }
        
    except Exception as e:
        logger.error(f"Error analyzing submission: {e}")
        return {
            'score_recommendation': None,
            'confidence': 0.0,
            'feedback': f"An error occurred during analysis: {str(e)}",
            'key_points': [],
            'improvement_areas': []
        }

def predict_student_performance(student_id, course_id, grades_data):
    """
    Predict a student's future performance based on past grades.
    
    Args:
        student_id: ID of the student
        course_id: ID of the course
        grades_data: DataFrame or list of past grades and related information
        
    Returns:
        dict: Prediction results
    """
    try:
        # Convert to DataFrame if it's a list
        if isinstance(grades_data, list):
            if not grades_data:
                return {
                    'prediction': None,
                    'confidence': 0.0,
                    'explanation': "Insufficient data for prediction"
                }
            
            grades_df = pd.DataFrame(grades_data)
        else:
            grades_df = grades_data
        
        # Check if we have enough data
        if len(grades_df) < 2:
            return {
                'prediction': None,
                'confidence': 0.0,
                'explanation': "Insufficient data for prediction"
            }
        
        # Analyze trend
        grades_df = grades_df.sort_values('timestamp')
        recent_grades = grades_df['score'].values[-3:]  # Get last 3 grades
        
        if len(recent_grades) >= 2:
            # Calculate trend direction
            trend = np.polyfit(range(len(recent_grades)), recent_grades, 1)[0]
            
            # Current average
            current_avg = grades_df['score'].mean()
            
            # Predict future performance
            if trend > 0:
                prediction = min(100, current_avg + (trend * 2))  # Project forward with ceiling of 100
                explanation = "Based on your improving grades trend, you're likely to continue improving."
                confidence = min(0.8, 0.5 + (abs(trend) / 10))  # Higher confidence with stronger trend
            elif trend < 0:
                prediction = max(0, current_avg + (trend * 2))  # Project forward with floor of 0
                explanation = "Based on your recent grades trend, you may need additional support to improve performance."
                confidence = min(0.8, 0.5 + (abs(trend) / 10))
            else:
                prediction = current_avg
                explanation = "Based on your consistent grades, your performance is likely to remain stable."
                confidence = 0.6
            
            return {
                'prediction': prediction,
                'confidence': confidence,
                'explanation': explanation,
                'trend': trend,
                'current_average': current_avg
            }
        else:
            # Not enough grades for trend analysis
            return {
                'prediction': grades_df['score'].mean(),
                'confidence': 0.4,
                'explanation': "Limited grade history available. Prediction is based on current average."
            }
            
    except Exception as e:
        logger.error(f"Error predicting student performance: {e}")
        return {
            'prediction': None,
            'confidence': 0.0,
            'explanation': f"An error occurred during prediction: {str(e)}"
        }

def generate_assignment_recommendations(student_id, course_id, student_data, course_data):
    """
    Generate personalized assignment recommendations for a student.
    
    Args:
        student_id: ID of the student
        course_id: ID of the course
        student_data: Dictionary with student performance data
        course_data: Dictionary with course information
        
    Returns:
        list: Recommended assignments or topics
    """
    try:
        recommendations = []
        
        # Identify weak areas based on past performance
        if 'past_assignments' in student_data and student_data['past_assignments']:
            assignments = student_data['past_assignments']
            
            # Group assignments by topic/category if available
            topic_scores = {}
            for assignment in assignments:
                topic = assignment.get('topic', 'general')
                score = assignment.get('score')
                
                if score is not None:
                    if topic not in topic_scores:
                        topic_scores[topic] = []
                    topic_scores[topic].append(score)
            
            # Calculate average scores by topic
            topic_averages = {topic: sum(scores)/len(scores) for topic, scores in topic_scores.items()}
            
            # Identify weakest topics (below 75%)
            weak_topics = [topic for topic, avg in topic_averages.items() if avg < 75]
            
            # Recommend practice on weak topics
            for topic in weak_topics:
                recommendations.append({
                    'type': 'practice',
                    'topic': topic,
                    'reason': f"Your average score in {topic} is {topic_averages[topic]:.1f}%. Additional practice could help improve your understanding."
                })
        
        # If we have learning style information, tailor recommendations
        if 'learning_style' in student_data:
            learning_style = student_data['learning_style']
            
            if learning_style == 'visual':
                recommendations.append({
                    'type': 'resource',
                    'description': "Visual learning resources like diagrams and videos",
                    'reason': "Based on your visual learning style preference"
                })
            elif learning_style == 'auditory':
                recommendations.append({
                    'type': 'resource',
                    'description': "Audio lectures and discussion groups",
                    'reason': "Based on your auditory learning style preference"
                })
            elif learning_style == 'kinesthetic':
                recommendations.append({
                    'type': 'resource',
                    'description': "Hands-on practice exercises and interactive simulations",
                    'reason': "Based on your preference for hands-on learning"
                })
        
        # Recommend advanced topics for high performers
        if 'overall_average' in student_data:
            overall_avg = student_data['overall_average']
            
            if overall_avg >= 90 and 'advanced_topics' in course_data:
                for topic in course_data['advanced_topics'][:2]:  # Limit to 2 advanced topics
                    recommendations.append({
                        'type': 'advanced_topic',
                        'topic': topic,
                        'reason': "Based on your strong performance, you might enjoy exploring this advanced topic"
                    })
        
        # Ensure we have at least one recommendation
        if not recommendations:
            recommendations.append({
                'type': 'general',
                'description': "Review course materials and practice exercises",
                'reason': "Regular review helps reinforce learning"
            })
        
        return recommendations
        
    except Exception as e:
        logger.error(f"Error generating assignment recommendations: {e}")
        return [{
            'type': 'error',
            'description': "Unable to generate personalized recommendations",
            'reason': f"An error occurred: {str(e)}"
        }]

def optimize_schedule(events, constraints, preferences):
    """
    Optimize a schedule based on events, constraints, and preferences.
    
    Args:
        events: List of events to schedule (with duration, deadline, etc.)
        constraints: Scheduling constraints (e.g., available time slots)
        preferences: User preferences (e.g., preferred times, breaks between events)
        
    Returns:
        list: Optimized schedule with recommended time slots
    """
    try:
        optimized_schedule = []
        
        # Sort events by priority and deadline
        sorted_events = sorted(events, key=lambda x: (x.get('priority', 5), x.get('deadline', datetime.max)))
        
        # Extract available time slots from constraints
        available_slots = constraints.get('available_slots', [])
        
        # If no available slots provided, create some reasonable defaults
        if not available_slots:
            # Create default availability (9 AM to 5 PM for the next 7 days)
            start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            for day in range(7):
                day_date = start_date + timedelta(days=day)
                # Skip weekends if specified in constraints
                if constraints.get('skip_weekends', False) and day_date.weekday() >= 5:
                    continue
                    
                # Add morning and afternoon slots
                available_slots.append({
                    'start': day_date.replace(hour=9, minute=0),
                    'end': day_date.replace(hour=12, minute=0)
                })
                available_slots.append({
                    'start': day_date.replace(hour=13, minute=0),
                    'end': day_date.replace(hour=17, minute=0)
                })
        
        # Get preferences
        min_break = preferences.get('min_break_minutes', 15)
        preferred_time = preferences.get('preferred_time', 'morning')
        
        # Sort available slots
        available_slots = sorted(available_slots, key=lambda x: x['start'])
        
        # First pass: assign high priority events to preferred times
        for event in sorted_events:
            duration_minutes = event.get('duration_minutes', 60)
            deadline = event.get('deadline')
            priority = event.get('priority', 5)
            
            # Find suitable slot
            best_slot = None
            best_slot_score = -1
            
            for slot in available_slots:
                # Skip slots that are in the past
                if slot['end'] < datetime.now():
                    continue
                    
                # Skip slots that are after the deadline
                if deadline and slot['start'] > deadline:
                    continue
                
                # Calculate available duration in this slot
                slot_duration = (slot['end'] - slot['start']).total_seconds() / 60
                
                # Skip if slot is too short
                if slot_duration < duration_minutes:
                    continue
                
                # Calculate score for this slot
                score = 0
                
                # Prefer slots further from the deadline for higher priority tasks
                if deadline:
                    days_until_deadline = (deadline - slot['start']).days
                    if priority <= 3:  # High priority
                        score += 10 if days_until_deadline <= 1 else 0  # High priority tasks close to deadline
                    else:
                        score += min(5, days_until_deadline)  # Lower priority tasks earlier if possible
                
                # Prefer morning/afternoon according to preference
                if preferred_time == 'morning' and 5 <= slot['start'].hour <= 12:
                    score += 5
                elif preferred_time == 'afternoon' and 12 < slot['start'].hour <= 17:
                    score += 5
                elif preferred_time == 'evening' and 17 < slot['start'].hour <= 22:
                    score += 5
                
                # If this is the best slot so far, save it
                if score > best_slot_score:
                    best_slot_score = score
                    best_slot = slot
            
            # If a suitable slot was found, schedule the event
            if best_slot:
                event_end_time = best_slot['start'] + timedelta(minutes=duration_minutes)
                
                # Create scheduled event
                scheduled_event = {
                    'id': event.get('id'),
                    'title': event.get('title'),
                    'start_time': best_slot['start'],
                    'end_time': event_end_time,
                    'duration_minutes': duration_minutes
                }
                optimized_schedule.append(scheduled_event)
                
                # Update the slot
                if event_end_time + timedelta(minutes=min_break) < best_slot['end']:
                    # If there's still time in this slot after the event and a break, update the slot
                    best_slot['start'] = event_end_time + timedelta(minutes=min_break)
                else:
                    # Otherwise, mark the slot as used by removing it
                    available_slots.remove(best_slot)
        
        return optimized_schedule
        
    except Exception as e:
        logger.error(f"Error optimizing schedule: {e}")
        return []
